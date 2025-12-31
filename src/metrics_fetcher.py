"""
Metrics Fetcher - Prometheus integration

Handles Prometheus queries, parses results, calculates baselines.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from prometheus_api_client import PrometheusConnect
from prometheus_api_client.utils import parse_datetime

from models import (
    PrometheusConfig,
    MetricData,
    MetricsSnapshot,
    TimeSeriesPoint,
    MetricQueries
)

logger = logging.getLogger(__name__)


class MetricsFetchError(Exception):
    """Raised when metric fetching fails"""
    pass


class MetricsFetcher:
    """
    Fetches metrics from Prometheus.
    
    Handles query execution, data parsing, and baseline calculation.
    """
    
    def __init__(self, config: PrometheusConfig):
        """Initialize with Prometheus config."""
        self.config = config
        self.prometheus = self._create_prometheus_client()
        logger.info(f"Connected to Prometheus at {config.url}")
    
    def _create_prometheus_client(self) -> PrometheusConnect:
        """Create Prometheus client."""
        headers = self.config.headers or {}
        
        return PrometheusConnect(
            url=self.config.url,
            disable_ssl=not self.config.verify_ssl,
            headers=headers
        )
    
    def query_range(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime,
        step: str = "30s"
    ) -> List[Dict]:
        """Execute PromQL range query."""
        try:
            logger.debug(f"Executing query: {query}")
            logger.debug(f"Time range: {start_time} to {end_time}")
            
            result = self.prometheus.custom_query_range(
                query=query,
                start_time=start_time,
                end_time=end_time,
                step=step
            )
            
            if not result:
                logger.warning(f"Query returned no data: {query}")
                return []
            
            logger.debug(f"Query returned {len(result)} series")
            return result
            
        except requests.exceptions.Timeout:
            raise MetricsFetchError(f"Query timeout after {self.config.timeout}s: {query}")
        except requests.exceptions.RequestException as e:
            raise MetricsFetchError(f"Failed to execute query: {e}")
        except Exception as e:
            raise MetricsFetchError(f"Unexpected error executing query: {e}")
    
    def query_instant(self, query: str) -> List[Dict]:
        """Execute instant PromQL query."""
        try:
            logger.debug(f"Executing instant query: {query}")
            result = self.prometheus.custom_query(query=query)
            
            if not result:
                logger.warning(f"Instant query returned no data: {query}")
                return []
            
            return result
            
        except Exception as e:
            raise MetricsFetchError(f"Failed to execute instant query: {e}")
    
    def parse_time_series(
        self,
        result: List[Dict],
        metric_name: str
    ) -> MetricData:
        """Parse Prometheus result into MetricData."""
        if not result:
            return MetricData(name=metric_name, values=[])
        
        # Usually we get one series, but handle multiple by averaging
        all_points: List[TimeSeriesPoint] = []
        
        for series in result:
            values = series.get("values", [])
            for timestamp, value in values:
                try:
                    # Prometheus returns timestamp as Unix timestamp
                    dt = datetime.fromtimestamp(float(timestamp))
                    val = float(value)
                    all_points.append(TimeSeriesPoint(timestamp=dt, value=val))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse data point: {e}")
                    continue
        
        # Sort by timestamp
        all_points.sort(key=lambda p: p.timestamp)
        
        logger.debug(f"Parsed {len(all_points)} points for {metric_name}")
        return MetricData(name=metric_name, values=all_points)
    
    def get_current_snapshot(
        self,
        service: str,
        queries: MetricQueries,
        lookback: str = "5m"
    ) -> MetricsSnapshot:
        """
        Get current metrics snapshot for a service.
        
        This fetches all relevant metrics and packages them
        into a single snapshot for analysis.
        
        Args:
            service: Service name
            queries: PromQL queries for each metric
            lookback: How far back to look (e.g., "5m")
        
        Returns:
            MetricsSnapshot with current values
        """
        now = datetime.utcnow()
        start_time = now - self._parse_duration(lookback)
        
        snapshot = MetricsSnapshot(
            timestamp=now,
            service=service
        )
        
        # Fetch latency metrics
        if queries.latency_p50:
            snapshot.latency_p50 = self._fetch_latest_value(
                queries.latency_p50, start_time, now
            )
        
        if queries.latency_p95:
            snapshot.latency_p95 = self._fetch_latest_value(
                queries.latency_p95, start_time, now
            )
        
        if queries.latency_p99:
            snapshot.latency_p99 = self._fetch_latest_value(
                queries.latency_p99, start_time, now
            )
        
        # Fetch error and request rates
        if queries.error_rate:
            snapshot.error_rate = self._fetch_latest_value(
                queries.error_rate, start_time, now
            )
        
        if queries.request_rate:
            snapshot.request_rate = self._fetch_latest_value(
                queries.request_rate, start_time, now
            )
        
        # Fetch resource usage
        if queries.cpu_usage:
            snapshot.cpu_usage = self._fetch_latest_value(
                queries.cpu_usage, start_time, now
            )
        
        if queries.memory_usage:
            snapshot.memory_usage = self._fetch_latest_value(
                queries.memory_usage, start_time, now
            )
        
        # Fetch masking signals
        if queries.retry_rate:
            snapshot.retry_rate = self._fetch_latest_value(
                queries.retry_rate, start_time, now
            )
        
        if queries.queue_depth:
            snapshot.queue_depth = self._fetch_latest_value(
                queries.queue_depth, start_time, now
            )
        
        if queries.connection_pool_usage:
            snapshot.connection_pool_usage = self._fetch_latest_value(
                queries.connection_pool_usage, start_time, now
            )
        
        logger.info(f"Fetched snapshot for {service}")
        return snapshot
    
    def calculate_baseline(
        self,
        query: str,
        baseline_window: str = "1h"
    ) -> Optional[float]:
        """
        Calculate baseline value for a metric over a time window.
        
        Uses average value over the baseline window as the baseline.
        This provides a reference point for detecting changes.
        
        Args:
            query: PromQL query for the metric
            baseline_window: Time window for baseline (e.g., "1h", "24h")
        
        Returns:
            Baseline value (average) or None if insufficient data
        """
        now = datetime.utcnow()
        start_time = now - self._parse_duration(baseline_window)
        
        try:
            result = self.query_range(query, start_time, now, step="1m")
            metric_data = self.parse_time_series(result, "baseline")
            
            if not metric_data.values:
                logger.warning(f"No data for baseline calculation")
                return None
            
            # Calculate average
            values = [p.value for p in metric_data.values]
            baseline = sum(values) / len(values)
            
            logger.debug(f"Calculated baseline: {baseline:.2f}")
            return baseline
            
        except MetricsFetchError as e:
            logger.error(f"Failed to calculate baseline: {e}")
            return None
    
    def calculate_percentage_change(
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
            Percentage change (e.g., 25.0 for 25% increase)
        """
        if baseline == 0:
            return 0.0 if current == 0 else float('inf')
        
        return ((current - baseline) / baseline) * 100.0
    
    def detect_trend(
        self,
        metric_data: MetricData,
        window_minutes: int = 5
    ) -> str:
        """
        Detect trend in metric data (increasing, decreasing, stable).
        
        Uses linear regression over the most recent window to determine trend.
        
        Args:
            metric_data: Time series data
            window_minutes: Window for trend analysis
        
        Returns:
            Trend direction: "increasing", "decreasing", or "stable"
        """
        if len(metric_data.values) < 2:
            return "stable"
        
        # Get points in the window
        cutoff_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        recent_points = [
            p for p in metric_data.values
            if p.timestamp >= cutoff_time
        ]
        
        if len(recent_points) < 2:
            return "stable"
        
        # Simple trend detection: compare first and last values
        # For production, you'd use linear regression
        first_val = recent_points[0].value
        last_val = recent_points[-1].value
        
        change_pct = abs((last_val - first_val) / first_val * 100.0) if first_val != 0 else 0
        
        # Consider stable if change is less than 5%
        if change_pct < 5.0:
            return "stable"
        
        return "increasing" if last_val > first_val else "decreasing"
    
    def _fetch_latest_value(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime
    ) -> Optional[float]:
        """
        Fetch the latest value for a metric query.
        
        Args:
            query: PromQL query
            start_time: Start of range
            end_time: End of range
        
        Returns:
            Latest value or None
        """
        try:
            result = self.query_range(query, start_time, end_time, step="30s")
            metric_data = self.parse_time_series(result, "temp")
            return metric_data.latest_value
        except MetricsFetchError as e:
            logger.warning(f"Failed to fetch metric: {e}")
            return None
    
    def _parse_duration(self, duration_str: str) -> timedelta:
        """Parse duration string (e.g., '5m', '1h') to timedelta."""
        duration_str = duration_str.strip()
        
        if duration_str.endswith('s'):
            return timedelta(seconds=int(duration_str[:-1]))
        elif duration_str.endswith('m'):
            return timedelta(minutes=int(duration_str[:-1]))
        elif duration_str.endswith('h'):
            return timedelta(hours=int(duration_str[:-1]))
        elif duration_str.endswith('d'):
            return timedelta(days=int(duration_str[:-1]))
        else:
            raise ValueError(f"Invalid duration format: {duration_str}")
    
    def health_check(self) -> bool:
        """Check if Prometheus is reachable."""
        try:
            # Simple query to test connectivity
            self.query_instant("up")
            logger.info("Prometheus health check passed")
            return True
        except Exception as e:
            logger.error(f"Prometheus health check failed: {e}")
            return False


def build_default_queries(service: str) -> MetricQueries:
    """
    Build default PromQL queries for a service.
    Uses standard Prometheus exporter metric names.
    """
    return MetricQueries(
        # Latency percentiles from histogram
        latency_p50=(
            f'histogram_quantile(0.50, '
            f'rate(http_request_duration_seconds_bucket{{job="{service}"}}[5m]))'
        ),
        latency_p95=(
            f'histogram_quantile(0.95, '
            f'rate(http_request_duration_seconds_bucket{{job="{service}"}}[5m]))'
        ),
        latency_p99=(
            f'histogram_quantile(0.99, '
            f'rate(http_request_duration_seconds_bucket{{job="{service}"}}[5m]))'
        ),
        
        # Error rate (5xx responses)
        error_rate=(
            f'sum(rate(http_requests_total{{job="{service}",status=~"5.."}}[5m])) '
            f'/ sum(rate(http_requests_total{{job="{service}"}}[5m])) * 100'
        ),
        
        # Request rate
        request_rate=(
            f'sum(rate(http_requests_total{{job="{service}"}}[5m]))'
        ),
        
        # CPU usage
        cpu_usage=(
            f'sum(rate(container_cpu_usage_seconds_total{{pod=~"{service}.*"}}[5m])) '
            f'/ sum(container_spec_cpu_quota{{pod=~"{service}.*"}} '
            f'/ container_spec_cpu_period{{pod=~"{service}.*"}}) * 100'
        ),
        
        # Memory usage
        memory_usage=(
            f'sum(container_memory_usage_bytes{{pod=~"{service}.*"}}) '
            f'/ sum(container_spec_memory_limit_bytes{{pod=~"{service}.*"}}) * 100'
        ),
        
        # Retry rate
        retry_rate=(
            f'sum(rate(http_request_retries_total{{job="{service}"}}[5m]))'
        ),
        
        # Queue depth
        queue_depth=(
            f'sum(queue_depth{{job="{service}"}})'
        ),
        
        # Connection pool usage
        connection_pool_usage=(
            f'sum(connection_pool_active{{job="{service}"}}) '
            f'/ sum(connection_pool_max{{job="{service}"}}) * 100'
        )
    )
