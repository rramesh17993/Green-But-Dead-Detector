"""
Unit tests for the detection engine

Run with:
    pytest tests/test_detector.py -v
    pytest tests/test_detector.py -v --cov=src
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from src.models import (
    DetectorPolicy,
    MetricsSnapshot,
    SignalDetection,
    DetectorState,
    ConfidenceLevel
)
from src.detector import Detector


@pytest.fixture
def basic_policy():
    """Create a basic detection policy for testing"""
    return DetectorPolicy(
        service="test-service",
        confidence={
            "min_signals": 3,
            "weights": {
                "latency": 2.0,
                "masking": 1.5,
                "illusions": 1.0
            }
        }
    )


@pytest.fixture
def detector(basic_policy):
    """Create detector instance"""
    return Detector(basic_policy)


@pytest.fixture
def healthy_snapshot():
    """Snapshot of a healthy system"""
    return MetricsSnapshot(
        timestamp=datetime.utcnow(),
        service="test-service",
        latency_p95=0.1,
        latency_p99=0.15,
        error_rate=0.1,
        cpu_usage=40.0,
        retry_rate=1.0
    )


class TestConfidenceCalculation:
    """Test confidence scoring logic"""
    
    def test_high_confidence_with_all_signal_types(self, detector):
        """Should have high confidence when all signal types present"""
        symptoms = [
            SignalDetection(
                signal_type="latency_p95_increase",
                description="p95 up",
                value=0.5,
                severity=0.8
            )
        ]
        
        illusions = [
            SignalDetection(
                signal_type="low_error_rate",
                description="errors low",
                value=0.1,
                severity=0.9
            )
        ]
        
        masking = [
            SignalDetection(
                signal_type="retry_spike",
                description="retries high",
                value=10.0,
                severity=0.7
            )
        ]
        
        score = detector._calculate_confidence(symptoms, illusions, masking)
        
        # With all three types and boost, should be high
        assert score > 0.6, f"Expected high confidence, got {score}"
    
    def test_low_confidence_with_few_signals(self, detector):
        """Should have low confidence with only 1-2 signals"""
        symptoms = [
            SignalDetection(
                signal_type="latency_p95_increase",
                description="p95 up",
                value=0.5,
                severity=0.5
            )
        ]
        
        score = detector._calculate_confidence(symptoms, [], [])
        
        assert score < 0.4, f"Expected low confidence with few signals, got {score}"
    
    def test_confidence_penalty_below_min_signals(self, detector):
        """Should apply penalty when below minimum signal count"""
        # Policy requires min_signals: 3
        symptoms = [
            SignalDetection(
                signal_type="latency_increase",
                description="test",
                value=1.0,
                severity=1.0
            )
        ]
        
        score = detector._calculate_confidence(symptoms, [], [])
        
        # Should be penalized for having only 1 signal when 3 required
        assert score < 0.5


class TestStateDetermination:
    """Test system state determination logic"""
    
    def test_green_but_dead_with_all_elements(self, detector):
        """Should detect green-but-dead with symptoms + illusions + masking"""
        symptoms = [Mock(spec=SignalDetection)]
        illusions = [Mock(spec=SignalDetection)]
        masking = [Mock(spec=SignalDetection)]
        
        state = detector._determine_state(symptoms, illusions, masking, 0.7)
        
        assert state == DetectorState.GREEN_BUT_DEAD
    
    def test_degraded_without_illusions(self, detector):
        """Should detect degraded when symptoms but no illusions"""
        symptoms = [Mock(spec=SignalDetection)]
        illusions = []
        masking = [Mock(spec=SignalDetection)]
        
        state = detector._determine_state(symptoms, illusions, masking, 0.7)
        
        assert state == DetectorState.DEGRADED
    
    def test_healthy_with_no_symptoms(self, detector):
        """Should be healthy with no symptoms"""
        state = detector._determine_state([], [], [], 0.3)
        
        assert state == DetectorState.HEALTHY
    
    def test_unknown_with_low_confidence(self, detector):
        """Should be unknown with very low confidence"""
        symptoms = [Mock(spec=SignalDetection)]
        
        state = detector._determine_state(symptoms, [], [], 0.1)
        
        assert state == DetectorState.UNKNOWN


class TestVerdictGeneration:
    """Test complete verdict generation"""
    
    def test_complete_verdict_structure(self, detector, healthy_snapshot):
        """Verdict should have all required fields"""
        signals = {
            'symptoms': [
                SignalDetection(
                    signal_type="latency_increase",
                    description="Latency up 50%",
                    value=0.3,
                    severity=0.8
                )
            ],
            'illusions': [
                SignalDetection(
                    signal_type="low_error_rate",
                    description="Errors at 0.2%",
                    value=0.2,
                    severity=0.9
                )
            ],
            'masking_signals': [
                SignalDetection(
                    signal_type="retry_spike",
                    description="Retries 3x",
                    value=3.0,
                    severity=0.7
                )
            ]
        }
        
        verdict = detector.detect(signals, healthy_snapshot)
        
        # Check required fields
        assert verdict.state is not None
        assert verdict.confidence is not None
        assert verdict.service == "test-service"
        assert verdict.summary != ""
        assert len(verdict.symptoms) == 1
        assert len(verdict.illusions) == 1
        assert len(verdict.masking_signals) == 1
    
    def test_verdict_is_critical_flag(self, detector, healthy_snapshot):
        """is_critical should be True for high-confidence green-but-dead"""
        signals = {
            'symptoms': [
                SignalDetection("test", "test", 1.0, severity=1.0),
                SignalDetection("test2", "test", 1.0, severity=1.0)
            ],
            'illusions': [
                SignalDetection("test3", "test", 1.0, severity=1.0)
            ],
            'masking_signals': [
                SignalDetection("test4", "test", 1.0, severity=1.0)
            ]
        }
        
        verdict = detector.detect(signals, healthy_snapshot)
        
        if verdict.state == DetectorState.GREEN_BUT_DEAD and \
           verdict.confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL]:
            assert verdict.is_critical


class TestImpactAssessment:
    """Test impact assessment logic"""
    
    def test_latency_impact(self, detector):
        """Should identify latency impact"""
        symptoms = [
            SignalDetection("latency_p95_increase", "test", 1.0, severity=1.0)
        ]
        
        impacts = detector._assess_impact(symptoms, [])
        
        assert any("slowness" in i.lower() for i in impacts)
    
    def test_retry_masking_impact(self, detector):
        """Should identify retry masking impact"""
        masking = [
            SignalDetection("retry_spike", "test", 1.0, severity=1.0)
        ]
        
        impacts = detector._assess_impact([], masking)
        
        assert any("retry" in i.lower() for i in impacts)
    
    def test_connection_pool_impact(self, detector):
        """Should identify connection pool issues"""
        masking = [
            SignalDetection("connection_pool_saturation", "test", 1.0, severity=1.0)
        ]
        
        impacts = detector._assess_impact([], masking)
        
        assert any("connection" in i.lower() for i in impacts)


class TestActionSuggestions:
    """Test suggested action generation"""
    
    def test_latency_actions(self, detector):
        """Should suggest latency-related actions"""
        symptoms = [
            SignalDetection("latency_increase", "test", 1.0, severity=1.0)
        ]
        
        actions = detector._suggest_actions(symptoms, [], [])
        
        assert any("dependency" in a.lower() or "database" in a.lower() 
                   for a in actions)
    
    def test_retry_actions(self, detector):
        """Should suggest retry investigation"""
        masking = [
            SignalDetection("retry_spike", "test", 1.0, severity=1.0)
        ]
        
        actions = detector._suggest_actions([], [], masking)
        
        assert any("retry" in a.lower() for a in actions)
    
    def test_action_count_limit(self, detector):
        """Should limit actions to reasonable number"""
        # Create many different signal types
        symptoms = [SignalDetection(f"symptom_{i}", "test", 1.0, severity=1.0) 
                   for i in range(10)]
        illusions = [SignalDetection(f"illusion_{i}", "test", 1.0, severity=1.0) 
                    for i in range(10)]
        masking = [SignalDetection(f"masking_{i}", "test", 1.0, severity=1.0) 
                  for i in range(10)]
        
        actions = detector._suggest_actions(symptoms, illusions, masking)
        
        # Should not overwhelm with too many actions
        assert len(actions) <= 8


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_empty_signals(self, detector, healthy_snapshot):
        """Should handle empty signals gracefully"""
        signals = {
            'symptoms': [],
            'illusions': [],
            'masking_signals': []
        }
        
        verdict = detector.detect(signals, healthy_snapshot)
        
        assert verdict.state == DetectorState.HEALTHY
        assert verdict.confidence == ConfidenceLevel.LOW
    
    def test_very_high_severity_signals(self, detector, healthy_snapshot):
        """Should handle very high severity signals"""
        signals = {
            'symptoms': [
                SignalDetection("critical", "test", 1000.0, severity=1.0)
            ],
            'illusions': [
                SignalDetection("critical", "test", 1000.0, severity=1.0)
            ],
            'masking_signals': [
                SignalDetection("critical", "test", 1000.0, severity=1.0)
            ]
        }
        
        verdict = detector.detect(signals, healthy_snapshot)
        
        # Should not crash, confidence should max out at 1.0
        assert verdict.confidence_score <= 1.0


class TestSummaryGeneration:
    """Test summary text generation"""
    
    def test_green_but_dead_summary(self, detector):
        """Green-but-dead summary should mention worst symptom"""
        symptoms = [
            SignalDetection(
                "latency_p99_increase",
                "p99 latency increased by 500%",
                5.0,
                severity=0.9
            )
        ]
        
        summary = detector._generate_summary(
            DetectorState.GREEN_BUT_DEAD,
            symptoms,
            ConfidenceLevel.HIGH
        )
        
        assert "green-but-dead" in summary.lower()
        assert "p99" in summary.lower()
    
    def test_healthy_summary(self, detector):
        """Healthy summary should be simple"""
        summary = detector._generate_summary(
            DetectorState.HEALTHY,
            [],
            ConfidenceLevel.LOW
        )
        
        assert "normal" in summary.lower() or "healthy" in summary.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
