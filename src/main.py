"""
Main Detector Service

Orchestrates metrics fetching, rule evaluation, and output.
"""

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

import structlog

from models import DetectorPolicy, DetectorState
from metrics_fetcher import MetricsFetcher, build_default_queries
from rule_engine import RuleEngine
from detector import Detector
from explainer import ExplainerFormatter, format_detection_log


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class GreenButDeadDetectorService:
    """
    Main service that orchestrates the detection pipeline.
    
    Pipeline:
    1. Load configuration
    2. Fetch metrics from Prometheus
    3. Calculate baselines
    4. Evaluate rules
    5. Produce verdict
    6. Format and output explanation
    """
    
    def __init__(self, config_path: str):
        """
        Initialize the detector service.
        
        Args:
            config_path: Path to detection policy YAML file
        """
        logger.info("Initializing Green-But-Dead Detector", config=config_path)
        
        # Load detection policy
        try:
            self.policy = RuleEngine.load_policy(config_path)
            logger.info("Loaded detection policy", service=self.policy.service)
        except Exception as e:
            logger.error("Failed to load policy", error=str(e))
            raise
        
        # Initialize components
        self.metrics_fetcher = MetricsFetcher(self.policy.prometheus)
        self.rule_engine = RuleEngine(self.policy)
        self.detector = Detector(self.policy)
        self.explainer = ExplainerFormatter(use_colors=True)
        
        logger.info("Service initialized successfully")
    
    def run_detection(self) -> int:
        """
        Run a single detection cycle.
        
        Returns:
            Exit code (0 = success, non-zero = error)
        """
        logger.info("Starting detection cycle", service=self.policy.service)
        
        try:
            # Step 1: Check Prometheus health
            if not self.metrics_fetcher.health_check():
                logger.error("Prometheus health check failed")
                return 1
            
            # Step 2: Get metric queries (use custom or build defaults)
            queries = self.policy.metric_queries or build_default_queries(
                self.policy.service
            )
            logger.info("Using metric queries", custom=self.policy.metric_queries is not None)
            
            # Step 3: Fetch current metrics snapshot
            logger.info("Fetching current metrics snapshot")
            snapshot = self.metrics_fetcher.get_current_snapshot(
                service=self.policy.service,
                queries=queries,
                lookback=self.policy.lookback_window
            )
            logger.info(
                "Snapshot fetched",
                latency_p95=snapshot.latency_p95,
                error_rate=snapshot.error_rate,
                cpu=snapshot.cpu_usage
            )
            
            # Step 4: Calculate baselines
            logger.info("Calculating baselines")
            baseline = self._calculate_baselines(queries)
            if baseline:
                snapshot.baseline = baseline
                logger.info("Baselines calculated", baseline=baseline)
            else:
                logger.warning("No baseline data available - detection may be limited")
            
            # Step 5: Evaluate rules
            logger.info("Evaluating detection rules")
            signals = self.rule_engine.evaluate_all(snapshot, baseline)
            
            total_signals = sum(len(s) for s in signals.values())
            logger.info(
                "Rule evaluation complete",
                total_signals=total_signals,
                symptoms=len(signals['symptoms']),
                illusions=len(signals['illusions']),
                masking=len(signals['masking_signals'])
            )
            
            # Step 6: Produce detection verdict
            logger.info("Producing detection verdict")
            verdict = self.detector.detect(signals, snapshot)
            
            logger.info(
                "Detection complete",
                state=verdict.state.value,
                confidence=verdict.confidence.value,
                confidence_score=verdict.confidence_score
            )
            
            # Step 7: Format and output explanation
            self._output_verdict(verdict)
            
            # Step 8: Determine exit code based on detection
            # Exit with specific codes for automation
            if verdict.is_critical:
                logger.warning("CRITICAL detection - exiting with code 2")
                return 2
            elif verdict.state == DetectorState.GREEN_BUT_DEAD:
                logger.warning("Green-but-dead detected - exiting with code 1")
                return 1
            else:
                logger.info("Detection cycle complete - system healthy")
                return 0
        
        except Exception as e:
            logger.error("Detection cycle failed", error=str(e), exc_info=True)
            return 3
    
    def _calculate_baselines(self, queries) -> Optional[dict]:
        """
        Calculate baseline values for all metrics.
        
        Args:
            queries: Metric queries to calculate baselines for
        
        Returns:
            Dictionary of baseline values or None
        """
        baseline = {}
        
        # Calculate baseline for each metric type
        if queries.latency_p50:
            val = self.metrics_fetcher.calculate_baseline(
                queries.latency_p50,
                self.policy.baseline_window
            )
            if val:
                baseline['latency_p50'] = val
        
        if queries.latency_p95:
            val = self.metrics_fetcher.calculate_baseline(
                queries.latency_p95,
                self.policy.baseline_window
            )
            if val:
                baseline['latency_p95'] = val
        
        if queries.latency_p99:
            val = self.metrics_fetcher.calculate_baseline(
                queries.latency_p99,
                self.policy.baseline_window
            )
            if val:
                baseline['latency_p99'] = val
        
        if queries.request_rate:
            val = self.metrics_fetcher.calculate_baseline(
                queries.request_rate,
                self.policy.baseline_window
            )
            if val:
                baseline['request_rate'] = val
        
        if queries.retry_rate:
            val = self.metrics_fetcher.calculate_baseline(
                queries.retry_rate,
                self.policy.baseline_window
            )
            if val:
                baseline['retry_rate'] = val
        
        if queries.queue_depth:
            val = self.metrics_fetcher.calculate_baseline(
                queries.queue_depth,
                self.policy.baseline_window
            )
            if val:
                baseline['queue_depth'] = val
        
        return baseline if baseline else None
    
    def _output_verdict(self, verdict):
        """
        Output the verdict in multiple formats.
        
        Args:
            verdict: Detection verdict to output
        """
        # 1. Structured log (for log aggregation)
        log_line = format_detection_log(verdict)
        logger.info(log_line)
        
        # 2. Rich terminal output (for human consumption)
        print("\n")
        print(self.explainer.format_verdict(verdict))
        print("\n")
        
        # 3. Plain text output to file (optional)
        output_file = Path("/tmp/green-but-dead-detector-latest.txt")
        try:
            output_file.write_text(self.explainer.format_plain(verdict))
            logger.info("Verdict written to file", path=str(output_file))
        except Exception as e:
            logger.warning("Failed to write verdict to file", error=str(e))


def main():
    """
    Main entry point for the detector service.
    
    Handles argument parsing and service initialization.
    """
    parser = argparse.ArgumentParser(
        description="Green-But-Dead Detector - Detect performance failures when everything looks healthy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with custom config
  python main.py --config /path/to/policy.yaml
  
  # Run with debug logging
  python main.py --config config/policy.yaml --log-level DEBUG
  
  # Dry run (test config without alerting)
  python main.py --config config/policy.yaml --dry-run
        """
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config/detector-policy.yaml',
        help='Path to detection policy YAML file (default: config/detector-policy.yaml)'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run detection without sending alerts'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='Green-But-Dead Detector v1.0.0'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Banner
    print("=" * 80)
    print("Green-But-Dead Detector")
    print("Detecting performance failures when everything looks healthy")
    print("=" * 80)
    print()
    
    # Check if config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Configuration file not found: {args.config}")
        print(f"\n✗ Error: Configuration file not found: {args.config}")
        print("\nPlease create a configuration file based on:")
        print("  config/detector-policy.example.yaml")
        return 1
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No alerts will be sent")
        print("[i] Running in DRY RUN mode - no alerts will be sent\n")
    
    # Initialize and run service
    try:
        service = GreenButDeadDetectorService(str(config_path))
        exit_code = service.run_detection()
        
        # Print exit code explanation
        if exit_code == 0:
            print("✓ System healthy")
        elif exit_code == 1:
            print("! Green-but-dead detected")
        elif exit_code == 2:
            print("! CRITICAL detection")
        else:
            print("✗ Detection failed")
        
        return exit_code
    
    except KeyboardInterrupt:
        logger.info("Detection interrupted by user")
        print("\\n\\n! Interrupted by user")
        return 130
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n\n✗ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
