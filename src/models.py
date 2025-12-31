"""
Data models for Green-But-Dead Detector

Pydantic models for type safety and validation.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class TrendDirection(str, Enum):
    """Direction of metric trend"""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"


class ConfidenceLevel(str, Enum):
    """Confidence in detection verdict"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DetectorState(str, Enum):
    """Overall system state assessment"""
    HEALTHY = "healthy"
    GREEN_BUT_DEAD = "green_but_dead"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# ==================== Configuration Models ====================

class LatencyConfig(BaseModel):
    """Latency detection thresholds"""
    p50_increase_pct: Optional[float] = None
    p95_increase_pct: float = 30.0
    p99_increase_pct: float = 40.0
    sustained_for: str = "5m"
    tail_divergence_threshold: Optional[float] = None


class ThroughputConfig(BaseModel):
    """Throughput detection thresholds"""
    rps_drop_pct: Optional[float] = None
    queue_depth_max: Optional[int] = None
    sustained_for: str = "5m"


class SymptomsConfig(BaseModel):
    """User-facing symptoms configuration"""
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    throughput: Optional[ThroughputConfig] = None


class AvailabilityIllusion(BaseModel):
    """Availability illusion thresholds"""
    error_rate_below: float = 1.0
    success_rate_above: Optional[float] = None


class ResourceIllusion(BaseModel):
    """Resource illusion thresholds"""
    cpu_below: float = 60.0
    memory_below: float = 80.0
    io_wait_below: Optional[float] = None


class IllusionsConfig(BaseModel):
    """Metrics that create false health signals"""
    availability: AvailabilityIllusion = Field(default_factory=AvailabilityIllusion)
    resources: ResourceIllusion = Field(default_factory=ResourceIllusion)


class RetryMasking(BaseModel):
    """Retry detection thresholds"""
    multiplier: float = 2.0
    absolute_threshold: Optional[float] = None


class QueueMasking(BaseModel):
    """Queue detection thresholds"""
    depth_trend: TrendDirection = TrendDirection.INCREASING
    saturation_pct: float = 85.0
    growth_rate_pct: Optional[float] = None


class ConnectionMasking(BaseModel):
    """Connection pool detection thresholds"""
    pool_saturation: float = 90.0
    wait_time_increase_pct: Optional[float] = None


class MaskingConfig(BaseModel):
    """Masking signal detection"""
    retries: Optional[RetryMasking] = None
    queues: Optional[QueueMasking] = None
    connections: Optional[ConnectionMasking] = None


class ConfidenceConfig(BaseModel):
    """Confidence scoring settings"""
    min_signals: int = 3
    weights: Dict[str, float] = {
        "latency": 2.0,
        "masking": 1.5,
        "illusions": 1.0,
        "throughput": 1.0
    }


class PrometheusConfig(BaseModel):
    """Prometheus connection settings"""
    url: str = "http://prometheus:9090"
    timeout: int = 30
    verify_ssl: bool = True
    headers: Optional[Dict[str, str]] = None


class MetricQueries(BaseModel):
    """PromQL queries for fetching metrics"""
    latency_p50: Optional[str] = None
    latency_p95: Optional[str] = None
    latency_p99: Optional[str] = None
    error_rate: Optional[str] = None
    request_rate: Optional[str] = None
    cpu_usage: Optional[str] = None
    memory_usage: Optional[str] = None
    retry_rate: Optional[str] = None
    queue_depth: Optional[str] = None
    connection_pool_usage: Optional[str] = None


class DetectorPolicy(BaseModel):
    """Complete detection policy"""
    service: str
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)
    symptoms: SymptomsConfig = Field(default_factory=SymptomsConfig)
    illusions: IllusionsConfig = Field(default_factory=IllusionsConfig)
    masking: MaskingConfig = Field(default_factory=MaskingConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    metric_queries: Optional[MetricQueries] = None
    lookback_window: str = "15m"
    baseline_window: str = "1h"


# ==================== Metric Data Models ====================

class TimeSeriesPoint(BaseModel):
    """A single point in a time series"""
    timestamp: datetime
    value: float


class MetricData(BaseModel):
    """Time series data for a single metric"""
    name: str
    values: List[TimeSeriesPoint]
    unit: Optional[str] = None

    @property
    def latest_value(self) -> Optional[float]:
        """Get the most recent value"""
        if not self.values:
            return None
        return max(self.values, key=lambda p: p.timestamp).value

    @property
    def oldest_value(self) -> Optional[float]:
        """Get the oldest value in the series"""
        if not self.values:
            return None
        return min(self.values, key=lambda p: p.timestamp).value


class MetricsSnapshot(BaseModel):
    """Current metrics snapshot"""
    timestamp: datetime
    service: str
    
    # Latency metrics
    latency_p50: Optional[float] = None
    latency_p95: Optional[float] = None
    latency_p99: Optional[float] = None
    
    # Throughput metrics
    request_rate: Optional[float] = None
    error_rate: Optional[float] = None
    
    # Resource metrics
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    
    # Masking signals
    retry_rate: Optional[float] = None
    queue_depth: Optional[float] = None
    connection_pool_usage: Optional[float] = None
    
    baseline: Optional[Dict[str, float]] = None


# ==================== Detection Result Models ====================

class SignalDetection(BaseModel):
    """A detected signal"""
    signal_type: str
    description: str
    value: float
    threshold: Optional[float] = None
    severity: float = 1.0
    metadata: Dict[str, Any] = {}


class DetectionVerdict(BaseModel):
    """Final detection verdict"""
    state: DetectorState
    confidence: ConfidenceLevel
    confidence_score: float
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    service: str
    
    # Detected signals
    symptoms: List[SignalDetection] = []
    illusions: List[SignalDetection] = []
    masking_signals: List[SignalDetection] = []
    
    # Analysis
    summary: str
    likely_impact: List[str] = []
    suggested_actions: List[str] = []
    metrics_snapshot: Optional[MetricsSnapshot] = None

    @property
    def total_signals(self) -> int:
        """Total number of signals detected"""
        return len(self.symptoms) + len(self.illusions) + len(self.masking_signals)

    @property
    def is_critical(self) -> bool:
        """Whether this is a critical detection"""
        return (
            self.state == DetectorState.GREEN_BUT_DEAD and
            self.confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL]
        )
