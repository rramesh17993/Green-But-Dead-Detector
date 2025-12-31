"""
Detector - Core detection logic

Combines signals to produce verdicts with confidence scoring.
"""

import logging
from typing import Dict, List, Optional

from models import (
    DetectorPolicy,
    MetricsSnapshot,
    DetectionVerdict,
    DetectorState,
    ConfidenceLevel,
    SignalDetection
)

logger = logging.getLogger(__name__)


class Detector:
    """
    Core detection engine that produces verdicts.
    
    Uses multi-signal approach:
    1. Collect signals from rules
    2. Calculate confidence
    3. Determine state
    4. Generate verdict
    """
    
    def __init__(self, policy: DetectorPolicy):
        """
        Initialize detector with policy.
        
        Args:
            policy: Detection policy configuration
        """
        self.policy = policy
        logger.info(f"Detector initialized for service: {policy.service}")
    
    def detect(
        self,
        signals: Dict[str, List[SignalDetection]],
        snapshot: MetricsSnapshot
    ) -> DetectionVerdict:
        """
        Produce a detection verdict from signals.
        
        This is the main detection logic that combines all signals
        into a final assessment with confidence scoring.
        
        Args:
            signals: Detected signals from rule engine
            snapshot: Current metrics snapshot
        
        Returns:
            DetectionVerdict with complete analysis
        """
        symptoms = signals.get('symptoms', [])
        illusions = signals.get('illusions', [])
        masking_signals = signals.get('masking_signals', [])
        
        logger.info(
            f"Analyzing {len(symptoms)} symptoms, "
            f"{len(illusions)} illusions, "
            f"{len(masking_signals)} masking signals"
        )
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence(
            symptoms, illusions, masking_signals
        )
        
        # Map to confidence level
        confidence_level = self._map_confidence_level(confidence_score)
        
        # Determine system state
        state = self._determine_state(
            symptoms, illusions, masking_signals, confidence_score
        )
        
        # Generate summary
        summary = self._generate_summary(state, symptoms, confidence_level)
        
        # Generate impact assessment
        likely_impact = self._assess_impact(symptoms, masking_signals)
        
        # Generate action recommendations
        suggested_actions = self._suggest_actions(
            symptoms, illusions, masking_signals
        )
        
        verdict = DetectionVerdict(
            state=state,
            confidence=confidence_level,
            confidence_score=confidence_score,
            service=self.policy.service,
            symptoms=symptoms,
            illusions=illusions,
            masking_signals=masking_signals,
            summary=summary,
            likely_impact=likely_impact,
            suggested_actions=suggested_actions,
            metrics_snapshot=snapshot
        )
        
        logger.info(
            f"Detection complete: {state.value} "
            f"(confidence: {confidence_level.value}, score: {confidence_score:.2f})"
        )
        
        return verdict
    
    def _calculate_confidence(
        self,
        symptoms: List[SignalDetection],
        illusions: List[SignalDetection],
        masking_signals: List[SignalDetection]
    ) -> float:
        """
        Calculate confidence score based on signal strength and count.
        
        Confidence increases with:
        - More signals detected
        - Higher severity signals
        - Presence of all three categories (symptoms + illusions + masking)
        
        Args:
            symptoms: Detected symptoms
            illusions: Detected illusions
            masking_signals: Detected masking signals
        
        Returns:
            Confidence score between 0.0 and 1.0
        """
        weights = self.policy.confidence.weights
        
        # Calculate weighted signal counts
        symptom_score = sum(s.severity for s in symptoms) * weights.get('latency', 1.0)
        illusion_score = sum(s.severity for s in illusions) * weights.get('illusions', 1.0)
        masking_score = sum(s.severity for s in masking_signals) * weights.get('masking', 1.0)
        
        # Total weighted score
        total_score = symptom_score + illusion_score + masking_score
        
        # Normalize to 0-1 range
        # We expect ~3-10 weighted signals for high confidence
        normalized_score = min(total_score / 10.0, 1.0)
        
        # Boost confidence if all three categories present
        if symptoms and illusions and masking_signals:
            # Bonus for having all contradiction elements
            normalized_score = min(normalized_score * 1.2, 1.0)
        
        # Penalty if below minimum signal count
        total_signals = len(symptoms) + len(illusions) + len(masking_signals)
        if total_signals < self.policy.confidence.min_signals:
            # Reduce confidence proportionally
            penalty = total_signals / self.policy.confidence.min_signals
            normalized_score *= penalty
        
        logger.debug(
            f"Confidence calculation: "
            f"symptoms={symptom_score:.2f}, "
            f"illusions={illusion_score:.2f}, "
            f"masking={masking_score:.2f}, "
            f"final={normalized_score:.2f}"
        )
        
        return normalized_score
    
    def _map_confidence_level(self, score: float) -> ConfidenceLevel:
        """
        Map confidence score to discrete level.
        
        Args:
            score: Confidence score (0.0-1.0)
        
        Returns:
            ConfidenceLevel enum
        """
        if score >= 0.8:
            return ConfidenceLevel.CRITICAL
        elif score >= 0.6:
            return ConfidenceLevel.HIGH
        elif score >= 0.4:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
    
    def _determine_state(
        self,
        symptoms: List[SignalDetection],
        illusions: List[SignalDetection],
        masking_signals: List[SignalDetection],
        confidence_score: float
    ) -> DetectorState:
        """
        Determine the overall system state.
        
        The key logic:
        - GREEN_BUT_DEAD: symptoms + illusions + masking (the contradiction)
        - DEGRADED: symptoms without illusions
        - HEALTHY: no significant symptoms
        
        Args:
            symptoms: Detected symptoms
            illusions: Detected illusions
            masking_signals: Detected masking signals
            confidence_score: Confidence score
        
        Returns:
            DetectorState enum
        """
        # Need minimum confidence to make a determination
        if confidence_score < 0.3:
            return DetectorState.UNKNOWN
        
        # Green-but-dead requires all three elements
        if symptoms and illusions and masking_signals:
            # This is the classic green-but-dead pattern:
            # Users hurt + looks healthy + something masking
            return DetectorState.GREEN_BUT_DEAD
        
        # If we have symptoms but no illusions, it's just degraded
        # (alerts should be firing)
        if symptoms and not illusions:
            return DetectorState.DEGRADED
        
        # If we have symptoms and illusions but no masking,
        # it's suspicious but might not be green-but-dead
        if symptoms and illusions and not masking_signals:
            # Still call it green-but-dead if confidence is high enough
            if confidence_score >= 0.6:
                return DetectorState.GREEN_BUT_DEAD
            else:
                return DetectorState.DEGRADED
        
        # No significant issues detected
        return DetectorState.HEALTHY
    
    def _generate_summary(
        self,
        state: DetectorState,
        symptoms: List[SignalDetection],
        confidence: ConfidenceLevel
    ) -> str:
        """
        Generate one-line summary of detection.
        
        Args:
            state: Detected state
            symptoms: Detected symptoms
            confidence: Confidence level
        
        Returns:
            Human-readable summary
        """
        if state == DetectorState.GREEN_BUT_DEAD:
            # Find most severe symptom
            if symptoms:
                worst = max(symptoms, key=lambda s: s.severity)
                return (
                    f"Green-but-dead detected: {worst.description} "
                    f"but system appears healthy (confidence: {confidence.value})"
                )
            return f"Green-but-dead pattern detected (confidence: {confidence.value})"
        
        elif state == DetectorState.DEGRADED:
            if symptoms:
                worst = max(symptoms, key=lambda s: s.severity)
                return f"System degraded: {worst.description}"
            return "System showing signs of degradation"
        
        elif state == DetectorState.HEALTHY:
            return "System operating normally"
        
        else:
            return "Insufficient data for determination"
    
    def _assess_impact(
        self,
        symptoms: List[SignalDetection],
        masking_signals: List[SignalDetection]
    ) -> List[str]:
        """
        Assess likely user impact based on detected signals.
        
        Args:
            symptoms: Detected symptoms
            masking_signals: Detected masking signals
        
        Returns:
            List of impact statements
        """
        impacts = []
        
        # Check latency symptoms
        latency_symptoms = [
            s for s in symptoms 
            if 'latency' in s.signal_type.lower()
        ]
        if latency_symptoms:
            impacts.append(
                "Users experiencing slowness and degraded response times"
            )
        
        # Check throughput symptoms
        throughput_symptoms = [
            s for s in symptoms 
            if 'rate' in s.signal_type.lower() or 'queue' in s.signal_type.lower()
        ]
        if throughput_symptoms:
            impacts.append(
                "Reduced system throughput affecting user capacity"
            )
        
        # Check retry masking
        retry_signals = [
            s for s in masking_signals 
            if 'retry' in s.signal_type.lower()
        ]
        if retry_signals:
            impacts.append(
                "Retries masking true failure rate - actual user experience worse than metrics suggest"
            )
        
        # Check queue masking
        queue_signals = [
            s for s in masking_signals 
            if 'queue' in s.signal_type.lower()
        ]
        if queue_signals:
            impacts.append(
                "Request queuing causing unpredictable delays"
            )
        
        # Check connection pool issues
        connection_signals = [
            s for s in masking_signals 
            if 'connection' in s.signal_type.lower()
        ]
        if connection_signals:
            impacts.append(
                "Connection pool exhaustion leading to request timeouts"
            )
        
        # Default if no specific impacts identified
        if not impacts:
            impacts.append("User experience may be degraded")
        
        return impacts
    
    def _suggest_actions(
        self,
        symptoms: List[SignalDetection],
        illusions: List[SignalDetection],
        masking_signals: List[SignalDetection]
    ) -> List[str]:
        """
        Generate investigation suggestions based on signals.
        
        Args:
            symptoms: Detected symptoms
            illusions: Detected illusions
            masking_signals: Detected masking signals
        
        Returns:
            List of suggested actions
        """
        actions = []
        
        # Latency-related actions
        if any('latency' in s.signal_type.lower() for s in symptoms):
            actions.append(
                "Check downstream dependency latency and response times"
            )
            actions.append(
                "Review database query performance and connection pools"
            )
        
        # Retry-related actions
        if any('retry' in s.signal_type.lower() for s in masking_signals):
            actions.append(
                "Investigate what's causing increased retry attempts"
            )
            actions.append(
                "Review timeout configurations and circuit breaker settings"
            )
        
        # Queue-related actions
        if any('queue' in s.signal_type.lower() for s in masking_signals):
            actions.append(
                "Examine queue backlog and processing rates"
            )
            actions.append(
                "Check for worker/thread starvation"
            )
        
        # Connection pool actions
        if any('connection' in s.signal_type.lower() for s in masking_signals):
            actions.append(
                "Review connection pool sizing and configuration"
            )
            actions.append(
                "Check for connection leaks or long-running transactions"
            )
        
        # Resource-related actions
        if any('cpu' in s.signal_type.lower() or 'memory' in s.signal_type.lower() for s in illusions):
            actions.append(
                "Despite low CPU/memory, check for IO wait or thread contention"
            )
            actions.append(
                "Review garbage collection metrics and pause times"
            )
        
        # General diagnostic actions
        actions.append(
            "Compare current behavior against historical baselines"
        )
        actions.append(
            "Check for recent deployments or configuration changes"
        )
        
        return actions[:6]  # Limit to top 6 most relevant actions
