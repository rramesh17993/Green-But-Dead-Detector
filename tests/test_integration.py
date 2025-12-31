"""
Integration test with mock Prometheus data

This test simulates a complete detection cycle with realistic data.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.models import DetectorPolicy, PrometheusConfig, MetricQueries
from src.main import GreenButDeadDetectorService


class TestIntegration:
    """Integration tests with mocked Prometheus"""
    
    @pytest.fixture
    def mock_prometheus_client(self):
        """Mock Prometheus client that returns realistic data"""
        mock_client = MagicMock()
        
        # Mock healthy baseline data (1 hour ago)
        baseline_time = datetime.utcnow() - timedelta(hours=1)
        mock_client.custom_query_range.side_effect = self._mock_query_range
        
        return mock_client
    
    def _mock_query_range(self, query, start_time, end_time, step):
        """Generate mock time series data based on query"""
        now = datetime.utcnow()
        
        # Simulate latency increase
        if 'histogram_quantile(0.95' in query:
            # p95 latency: starts at 0.1s, increases to 0.2s
            return [{
                'values': [
                    [now.timestamp() - 300, '0.10'],
                    [now.timestamp() - 240, '0.12'],
                    [now.timestamp() - 180, '0.15'],
                    [now.timestamp() - 120, '0.18'],
                    [now.timestamp() - 60, '0.20'],
                    [now.timestamp(), '0.20']
                ]
            }]
        
        elif 'histogram_quantile(0.99' in query:
            # p99 latency: higher increase
            return [{
                'values': [
                    [now.timestamp() - 300, '0.15'],
                    [now.timestamp() - 240, '0.20'],
                    [now.timestamp() - 180, '0.30'],
                    [now.timestamp() - 120, '0.40'],
                    [now.timestamp() - 60, '0.50'],
                    [now.timestamp(), '0.50']
                ]
            }]
        
        elif 'error_rate' in query or '5..' in query:
            # Error rate stays low
            return [{
                'values': [
                    [now.timestamp() - 300, '0.2'],
                    [now.timestamp() - 240, '0.2'],
                    [now.timestamp() - 180, '0.3'],
                    [now.timestamp() - 120, '0.2'],
                    [now.timestamp() - 60, '0.3'],
                    [now.timestamp(), '0.2']
                ]
            }]
        
        elif 'cpu' in query.lower():
            # CPU stays normal
            return [{
                'values': [
                    [now.timestamp() - 300, '45.0'],
                    [now.timestamp() - 240, '43.0'],
                    [now.timestamp() - 180, '47.0'],
                    [now.timestamp() - 120, '44.0'],
                    [now.timestamp() - 60, '46.0'],
                    [now.timestamp(), '45.0']
                ]
            }]
        
        elif 'retry' in query.lower():
            # Retries spike
            return [{
                'values': [
                    [now.timestamp() - 300, '1.0'],
                    [now.timestamp() - 240, '1.5'],
                    [now.timestamp() - 180, '2.5'],
                    [now.timestamp() - 120, '3.0'],
                    [now.timestamp() - 60, '3.5'],
                    [now.timestamp(), '3.5']
                ]
            }]
        
        else:
            # Default: stable values
            return [{
                'values': [
                    [now.timestamp() - 300, '100.0'],
                    [now.timestamp(), '100.0']
                ]
            }]
    
    def test_green_but_dead_detection_scenario(self, mock_prometheus_client):
        """
        Test complete detection cycle for classic green-but-dead scenario:
        - Latency increases significantly
        - Error rate stays low
        - CPU stays normal
        - Retries spike
        """
        # Create test policy
        policy_dict = {
            'service': 'test-api',
            'prometheus': {
                'url': 'http://test-prometheus:9090'
            },
            'symptoms': {
                'latency': {
                    'p95_increase_pct': 30.0,
                    'p99_increase_pct': 40.0,
                    'sustained_for': '5m'
                }
            },
            'illusions': {
                'availability': {
                    'error_rate_below': 1.0
                },
                'resources': {
                    'cpu_below': 60.0
                }
            },
            'masking': {
                'retries': {
                    'multiplier': 2.0
                }
            },
            'confidence': {
                'min_signals': 3,
                'weights': {
                    'latency': 2.0,
                    'masking': 1.5,
                    'illusions': 1.0
                }
            }
        }
        
        with patch('src.metrics_fetcher.PrometheusConnect', return_value=mock_prometheus_client):
            policy = DetectorPolicy(**policy_dict)
            
            # Import and test detection components
            from src.metrics_fetcher import MetricsFetcher, build_default_queries
            from src.rule_engine import RuleEngine
            from src.detector import Detector
            
            fetcher = MetricsFetcher(policy.prometheus)
            engine = RuleEngine(policy)
            detector = Detector(policy)
            
            # Get metrics
            queries = build_default_queries(policy.service)
            snapshot = fetcher.get_current_snapshot(
                policy.service,
                queries,
                '15m'
            )
            
            # Calculate baselines
            baseline = {
                'latency_p95': 0.10,
                'latency_p99': 0.15,
                'retry_rate': 1.0
            }
            
            # Evaluate rules
            signals = engine.evaluate_all(snapshot, baseline)
            
            # Produce verdict
            verdict = detector.detect(signals, snapshot)
            
            # Assertions
            assert len(signals['symptoms']) > 0, "Should detect latency symptoms"
            assert len(signals['illusions']) > 0, "Should detect healthy-looking metrics"
            assert len(signals['masking_signals']) > 0, "Should detect retry masking"
            
            # The key test: Did we detect green-but-dead?
            from src.models import DetectorState, ConfidenceLevel
            assert verdict.state == DetectorState.GREEN_BUT_DEAD, \
                f"Expected GREEN_BUT_DEAD, got {verdict.state}"
            
            assert verdict.confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL], \
                f"Expected high confidence, got {verdict.confidence}"
            
            assert verdict.total_signals >= 3, \
                "Should have multiple confirming signals"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
