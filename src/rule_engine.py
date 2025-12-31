"""
Rule Engine - YAML-driven detection rules

Loads and evaluates detection rules from configuration.
"""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

import yaml

from models import (
    DetectorPolicy,
    MetricsSnapshot,
    SignalDetection,
    LatencyConfig,
    ThroughputConfig,
    AvailabilityIllusion,
    ResourceIllusion,
    RetryMasking,
    QueueMasking,
    ConnectionMasking,
    TrendDirection
)

logger = logging.getLogger(__name__)


class RuleLoadError(Exception):
    """Raised when rule loading fails"""
    pass


class RuleEngine:
    """
    Evaluates detection rules against metric snapshots.
    
    The rule engine is stateless - it takes configuration and metrics,
    and produces signal detections. This makes it easy to test and reason about.
    
    Usage:
        policy = RuleEngine.load_policy("config/policy.yaml")
        engine = RuleEngine(policy)
        signals = engine.evaluate_all(snapshot, baseline)
    """
    
    def __init__(self, policy: DetectorPolicy):
        """
        Initialize rule engine with a detection policy.
        
        Args:
            policy: Loaded detection policy configuration
        """
        self.policy = policy
        logger.info(f"Rule engine initialized for service: {policy.service}")
    
    @classmethod
    def load_policy(cls, config_path: str) -> DetectorPolicy:
        """
        Load detection policy from YAML file.
        
        Args:
            config_path: Path to YAML configuration file
        
        Returns:
            Parsed DetectorPolicy object
        
        Raises:
            RuleLoadError: If config file cannot be loaded or parsed
        """
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise RuleLoadError(f"Config file not found: {config_path}")
        
        try:
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f)
            
            logger.info(f"Loaded configuration from {config_path}")
            
            # Parse and validate with Pydantic
            policy = DetectorPolicy(**config_data)
            
            logger.info(f"Configuration validated successfully")
            return policy
            
        except yaml.YAMLError as e:
            raise RuleLoadError(f"Invalid YAML syntax: {e}")
        except Exception as e:
            raise RuleLoadError(f"Failed to parse configuration: {e}")
    
    def evaluate_all(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]] = None
    ) -> Dict[str, List[SignalDetection]]:
        """
        Evaluate all rules against a metrics snapshot.
        
        This is the main entry point for rule evaluation. It runs all
        detection categories and returns organized results.
        
        Args:
            snapshot: Current metrics snapshot
            baseline: Baseline values for comparison (optional)
        
        Returns:
            Dictionary with keys: 'symptoms', 'illusions', 'masking_signals'
        """
        logger.info(f"Evaluating rules for {snapshot.service}")
        
        results = {
            'symptoms': [],
            'illusions': [],
            'masking_signals': []
        }
        
        # Evaluate symptoms (things that hurt users)
        results['symptoms'].extend(
            self.evaluate_latency_symptoms(snapshot, baseline)
        )
        results['symptoms'].extend(
            self.evaluate_throughput_symptoms(snapshot, baseline)
        )
        
        # Evaluate illusions (things that look healthy but aren't)
        results['illusions'].extend(
            self.evaluate_availability_illusions(snapshot)
        )
        results['illusions'].extend(
            self.evaluate_resource_illusions(snapshot)
        )
        
        # Evaluate masking signals (things hiding the problem)
        results['masking_signals'].extend(
            self.evaluate_retry_masking(snapshot, baseline)
        )
        results['masking_signals'].extend(
            self.evaluate_queue_masking(snapshot, baseline)
        )
        results['masking_signals'].extend(
            self.evaluate_connection_masking(snapshot, baseline)
        )
        
        # Log summary
        total = sum(len(signals) for signals in results.values())
        logger.info(
            f"Evaluation complete: {total} signals detected "
            f"({len(results['symptoms'])} symptoms, "
            f"{len(results['illusions'])} illusions, "
            f"{len(results['masking_signals'])} masking)"
        )
        
        return results
    
    # ==================== Symptom Evaluation ====================
    
    def evaluate_latency_symptoms(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]]
    ) -> List[SignalDetection]:
        """
        Evaluate latency-based symptoms.
        
        Checks if latency percentiles have increased beyond thresholds.
        
        Args:
            snapshot: Current metrics
            baseline: Baseline values
        
        Returns:
            List of detected latency symptoms
        """
        signals = []
        config = self.policy.symptoms.latency
        
        if baseline is None:
            logger.warning("No baseline provided for latency evaluation")
            return signals
        
        # Check p50 latency increase
        if config.p50_increase_pct and snapshot.latency_p50:
            baseline_p50 = baseline.get('latency_p50')
            if baseline_p50:
                pct_change = self._calculate_percentage_change(
                    snapshot.latency_p50, baseline_p50
                )
                
                if pct_change >= config.p50_increase_pct:
                    signals.append(SignalDetection(
                        signal_type="latency_p50_increase",
                        description=f"p50 latency increased by {pct_change:.1f}%",
                        value=snapshot.latency_p50,
                        threshold=baseline_p50 * (1 + config.p50_increase_pct / 100),
                        severity=min(pct_change / config.p50_increase_pct, 1.0),
                        metadata={
                            "baseline": baseline_p50,
                            "current": snapshot.latency_p50,
                            "percentage_change": pct_change
                        }
                    ))
        
        # Check p95 latency increase
        if config.p95_increase_pct and snapshot.latency_p95:
            baseline_p95 = baseline.get('latency_p95')
            if baseline_p95:
                pct_change = self._calculate_percentage_change(
                    snapshot.latency_p95, baseline_p95
                )
                
                if pct_change >= config.p95_increase_pct:
                    signals.append(SignalDetection(
                        signal_type="latency_p95_increase",
                        description=f"p95 latency increased by {pct_change:.1f}%",
                        value=snapshot.latency_p95,
                        threshold=baseline_p95 * (1 + config.p95_increase_pct / 100),
                        severity=min(pct_change / config.p95_increase_pct, 1.0),
                        metadata={
                            "baseline": baseline_p95,
                            "current": snapshot.latency_p95,
                            "percentage_change": pct_change
                        }
                    ))
        
        # Check p99 latency increase
        if config.p99_increase_pct and snapshot.latency_p99:
            baseline_p99 = baseline.get('latency_p99')
            if baseline_p99:
                pct_change = self._calculate_percentage_change(
                    snapshot.latency_p99, baseline_p99
                )
                
                if pct_change >= config.p99_increase_pct:
                    signals.append(SignalDetection(
                        signal_type="latency_p99_increase",
                        description=f"p99 latency increased by {pct_change:.1f}%",
                        value=snapshot.latency_p99,
                        threshold=baseline_p99 * (1 + config.p99_increase_pct / 100),
                        severity=min(pct_change / config.p99_increase_pct, 1.0),
                        metadata={
                            "baseline": baseline_p99,
                            "current": snapshot.latency_p99,
                            "percentage_change": pct_change
                        }
                    ))
        
        # Check tail latency divergence (p99 - p50)
        if (config.tail_divergence_threshold and 
            snapshot.latency_p99 and snapshot.latency_p50):
            divergence = snapshot.latency_p99 - snapshot.latency_p50
            
            if divergence >= config.tail_divergence_threshold:
                signals.append(SignalDetection(
                    signal_type="tail_latency_divergence",
                    description=f"Tail latency divergence: {divergence:.3f}s",
                    value=divergence,
                    threshold=config.tail_divergence_threshold,
                    severity=min(divergence / config.tail_divergence_threshold, 1.0),
                    metadata={
                        "p50": snapshot.latency_p50,
                        "p99": snapshot.latency_p99,
                        "divergence": divergence
                    }
                ))
        
        return signals
    
    def evaluate_throughput_symptoms(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]]
    ) -> List[SignalDetection]:
        """
        Evaluate throughput-based symptoms.
        
        Checks if request rate has dropped significantly.
        
        Args:
            snapshot: Current metrics
            baseline: Baseline values
        
        Returns:
            List of detected throughput symptoms
        """
        signals = []
        
        if self.policy.symptoms.throughput is None:
            return signals
        
        config = self.policy.symptoms.throughput
        
        if baseline is None:
            logger.warning("No baseline provided for throughput evaluation")
            return signals
        
        # Check request rate drop
        if config.rps_drop_pct and snapshot.request_rate:
            baseline_rps = baseline.get('request_rate')
            if baseline_rps:
                pct_change = self._calculate_percentage_change(
                    snapshot.request_rate, baseline_rps
                )
                
                if pct_change <= -config.rps_drop_pct:
                    signals.append(SignalDetection(
                        signal_type="request_rate_drop",
                        description=f"Request rate dropped by {abs(pct_change):.1f}%",
                        value=snapshot.request_rate,
                        threshold=baseline_rps * (1 - config.rps_drop_pct / 100),
                        severity=min(abs(pct_change) / config.rps_drop_pct, 1.0),
                        metadata={
                            "baseline": baseline_rps,
                            "current": snapshot.request_rate,
                            "percentage_change": pct_change
                        }
                    ))
        
        # Check queue depth
        if config.queue_depth_max and snapshot.queue_depth:
            if snapshot.queue_depth >= config.queue_depth_max:
                signals.append(SignalDetection(
                    signal_type="queue_depth_exceeded",
                    description=f"Queue depth at {snapshot.queue_depth}",
                    value=snapshot.queue_depth,
                    threshold=config.queue_depth_max,
                    severity=min(snapshot.queue_depth / config.queue_depth_max, 1.0),
                    metadata={
                        "current": snapshot.queue_depth,
                        "max": config.queue_depth_max
                    }
                ))
        
        return signals
    
    # ==================== Illusion Evaluation ====================
    
    def evaluate_availability_illusions(
        self,
        snapshot: MetricsSnapshot
    ) -> List[SignalDetection]:
        """
        Evaluate availability illusions.
        
        Detects when error rates are low (appearing healthy) despite other problems.
        
        Args:
            snapshot: Current metrics
        
        Returns:
            List of detected illusions
        """
        signals = []
        config = self.policy.illusions.availability
        
        # Check if error rate is deceptively low
        if snapshot.error_rate is not None:
            if snapshot.error_rate < config.error_rate_below:
                signals.append(SignalDetection(
                    signal_type="low_error_rate_illusion",
                    description=f"Error rate at {snapshot.error_rate:.2f}% (appears healthy)",
                    value=snapshot.error_rate,
                    threshold=config.error_rate_below,
                    severity=1.0 - (snapshot.error_rate / config.error_rate_below),
                    metadata={
                        "error_rate": snapshot.error_rate,
                        "threshold": config.error_rate_below
                    }
                ))
        
        # Check success rate if configured
        if config.success_rate_above and snapshot.error_rate is not None:
            success_rate = 100.0 - snapshot.error_rate
            if success_rate > config.success_rate_above:
                signals.append(SignalDetection(
                    signal_type="high_success_rate_illusion",
                    description=f"Success rate at {success_rate:.2f}% (appears healthy)",
                    value=success_rate,
                    threshold=config.success_rate_above,
                    severity=min(success_rate / config.success_rate_above, 1.0),
                    metadata={
                        "success_rate": success_rate,
                        "threshold": config.success_rate_above
                    }
                ))
        
        return signals
    
    def evaluate_resource_illusions(
        self,
        snapshot: MetricsSnapshot
    ) -> List[SignalDetection]:
        """
        Evaluate resource usage illusions.
        
        Detects when CPU/memory are low (appearing healthy) despite performance issues.
        
        Args:
            snapshot: Current metrics
        
        Returns:
            List of detected illusions
        """
        signals = []
        config = self.policy.illusions.resources
        
        # Check if CPU usage is deceptively low
        if snapshot.cpu_usage is not None:
            if snapshot.cpu_usage < config.cpu_below:
                signals.append(SignalDetection(
                    signal_type="low_cpu_illusion",
                    description=f"CPU usage at {snapshot.cpu_usage:.1f}% (appears healthy)",
                    value=snapshot.cpu_usage,
                    threshold=config.cpu_below,
                    severity=1.0 - (snapshot.cpu_usage / config.cpu_below),
                    metadata={
                        "cpu_usage": snapshot.cpu_usage,
                        "threshold": config.cpu_below
                    }
                ))
        
        # Check if memory usage is deceptively low
        if snapshot.memory_usage is not None:
            if snapshot.memory_usage < config.memory_below:
                signals.append(SignalDetection(
                    signal_type="low_memory_illusion",
                    description=f"Memory usage at {snapshot.memory_usage:.1f}% (appears healthy)",
                    value=snapshot.memory_usage,
                    threshold=config.memory_below,
                    severity=1.0 - (snapshot.memory_usage / config.memory_below),
                    metadata={
                        "memory_usage": snapshot.memory_usage,
                        "threshold": config.memory_below
                    }
                ))
        
        return signals
    
    # ==================== Masking Signal Evaluation ====================
    
    def evaluate_retry_masking(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]]
    ) -> List[SignalDetection]:
        """
        Evaluate retry-based masking signals.
        
        Detects when retries are hiding failures.
        
        Args:
            snapshot: Current metrics
            baseline: Baseline values
        
        Returns:
            List of detected masking signals
        """
        signals = []
        
        if self.policy.masking.retries is None:
            return signals
        
        config = self.policy.masking.retries
        
        if snapshot.retry_rate is None:
            return signals
        
        # Check retry rate multiplier against baseline
        if baseline and 'retry_rate' in baseline:
            baseline_retries = baseline['retry_rate']
            if baseline_retries > 0:
                multiplier = snapshot.retry_rate / baseline_retries
                
                if multiplier >= config.multiplier:
                    signals.append(SignalDetection(
                        signal_type="retry_spike",
                        description=f"Retry rate increased {multiplier:.1f}× baseline",
                        value=snapshot.retry_rate,
                        threshold=baseline_retries * config.multiplier,
                        severity=min(multiplier / config.multiplier, 1.0),
                        metadata={
                            "baseline": baseline_retries,
                            "current": snapshot.retry_rate,
                            "multiplier": multiplier
                        }
                    ))
        
        # Check absolute retry threshold if configured
        if config.absolute_threshold:
            if snapshot.retry_rate >= config.absolute_threshold:
                signals.append(SignalDetection(
                    signal_type="high_retry_rate",
                    description=f"Retry rate at {snapshot.retry_rate:.2f}/s",
                    value=snapshot.retry_rate,
                    threshold=config.absolute_threshold,
                    severity=min(snapshot.retry_rate / config.absolute_threshold, 1.0),
                    metadata={
                        "retry_rate": snapshot.retry_rate,
                        "threshold": config.absolute_threshold
                    }
                ))
        
        return signals
    
    def evaluate_queue_masking(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]]
    ) -> List[SignalDetection]:
        """
        Evaluate queue-based masking signals.
        
        Detects when queues are hiding latency issues.
        
        Args:
            snapshot: Current metrics
            baseline: Baseline values
        
        Returns:
            List of detected masking signals
        """
        signals = []
        
        if self.policy.masking.queues is None:
            return signals
        
        config = self.policy.masking.queues
        
        if snapshot.queue_depth is None:
            return signals
        
        # Check queue saturation
        if snapshot.queue_depth > 100:  # Example threshold
            saturation_pct = (snapshot.queue_depth / 100) * 100
            
            if saturation_pct >= config.saturation_pct:
                signals.append(SignalDetection(
                    signal_type="queue_saturation",
                    description=f"Queue at {saturation_pct:.1f}% capacity",
                    value=snapshot.queue_depth,
                    threshold=config.saturation_pct,
                    severity=min(saturation_pct / 100, 1.0),
                    metadata={
                        "queue_depth": snapshot.queue_depth,
                        "saturation": saturation_pct
                    }
                ))
        
        # Check queue growth trend
        if baseline and 'queue_depth' in baseline:
            baseline_depth = baseline['queue_depth']
            if snapshot.queue_depth > baseline_depth:
                if config.depth_trend == TrendDirection.INCREASING:
                    signals.append(SignalDetection(
                        signal_type="queue_growth",
                        description=f"Queue depth growing (now {snapshot.queue_depth})",
                        value=snapshot.queue_depth,
                        threshold=baseline_depth,
                        severity=min(snapshot.queue_depth / baseline_depth, 1.0),
                        metadata={
                            "baseline": baseline_depth,
                            "current": snapshot.queue_depth
                        }
                    ))
        
        return signals
    
    def evaluate_connection_masking(
        self,
        snapshot: MetricsSnapshot,
        baseline: Optional[Dict[str, float]]
    ) -> List[SignalDetection]:
        """
        Evaluate connection pool masking signals.
        
        Detects when connection pool exhaustion is hiding problems.
        
        Args:
            snapshot: Current metrics
            baseline: Baseline values
        
        Returns:
            List of detected masking signals
        """
        signals = []
        
        if self.policy.masking.connections is None:
            return signals
        
        config = self.policy.masking.connections
        
        if snapshot.connection_pool_usage is None:
            return signals
        
        # Check connection pool saturation
        if snapshot.connection_pool_usage >= config.pool_saturation:
            signals.append(SignalDetection(
                signal_type="connection_pool_saturation",
                description=f"Connection pool at {snapshot.connection_pool_usage:.1f}%",
                value=snapshot.connection_pool_usage,
                threshold=config.pool_saturation,
                severity=min(snapshot.connection_pool_usage / 100, 1.0),
                metadata={
                    "pool_usage": snapshot.connection_pool_usage,
                    "threshold": config.pool_saturation
                }
            ))
        
        return signals
    
    # ==================== Helper Methods ====================
    
    def _calculate_percentage_change(
        self,
        current: float,
        baseline: float
    ) -> float:
        """
        Calculate percentage change from baseline.
        
        Args:
            current: Current value
            baseline: Baseline value
        
        Returns:
            Percentage change
        """
        if baseline == 0:
            return 0.0 if current == 0 else float('inf')
        
        return ((current - baseline) / baseline) * 100.0
