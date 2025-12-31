# Configuration Guide

Complete guide to configuring the Green-But-Dead Detector.

## Table of Contents

- [Configuration File Structure](#configuration-file-structure)
- [Symptoms Configuration](#symptoms-configuration)
- [Illusions Configuration](#illusions-configuration)
- [Masking Configuration](#masking-configuration)
- [Confidence Configuration](#confidence-configuration)
- [Custom Metric Queries](#custom-metric-queries)
- [Tuning Guide](#tuning-guide)

## Configuration File Structure

The detector uses a single YAML configuration file with five main sections:

```yaml
service: your-service-name
prometheus: {...}
symptoms: {...}
illusions: {...}
masking: {...}
confidence: {...}
```

## Symptoms Configuration

Symptoms detect **real user pain**. These are the things that actually hurt your users.

### Latency Symptoms

```yaml
symptoms:
  latency:
    # Percentage increase thresholds
    p50_increase_pct: 25    # Median latency up 25%
    p95_increase_pct: 30    # 95th percentile up 30%
    p99_increase_pct: 40    # 99th percentile up 40%
    
    # Duration
    sustained_for: 5m       # Must persist for 5 minutes
    
    # Tail latency
    tail_divergence_threshold: 0.5  # p99-p50 gap (seconds)
```

**Tuning advice:**
- Start with higher percentages (30-50%)
- Gradually lower as you gain confidence
- p99 should have higher threshold than p95
- `sustained_for` prevents flapping on transient spikes

### Throughput Symptoms

```yaml
symptoms:
  throughput:
    rps_drop_pct: 20        # Request rate drops by 20%
    queue_depth_max: 1000   # Queue exceeds 1000 items
    sustained_for: 5m
```

**Tuning advice:**
- Only enable if you care about throughput drops
- Queue depth depends on your system's queue size
- Can indicate upstream throttling or cascading failures

## Illusions Configuration

Illusions detect metrics that **look healthy** when they shouldn't.

### Availability Illusions

```yaml
illusions:
  availability:
    error_rate_below: 1.0       # <1% errors looks healthy
    success_rate_above: 99.0    # >99% success looks healthy
```

**Philosophy:**
- These thresholds define "appears healthy"
- Detection triggers when latency is bad BUT errors are low
- This creates the "contradiction" we're looking for

**Tuning advice:**
- Set based on your normal error budget
- If you normally have 0.1% errors, set `error_rate_below: 0.5`
- This helps detect when retries are masking failures

### Resource Illusions

```yaml
illusions:
  resources:
    cpu_below: 60.0             # CPU <60% looks healthy
    memory_below: 80.0          # Memory <80% looks healthy
    io_wait_below: 10.0         # IO wait <10% looks healthy
```

**Philosophy:**
- Low CPU/memory doesn't always mean healthy
- Could indicate thread starvation or IO blocking
- Detection triggers when latency is bad BUT resources are low

**Tuning advice:**
- Set based on your normal operating ranges
- If you typically run at 40% CPU, set `cpu_below: 50`
- Add `io_wait_below` if you have IO-heavy workloads

## Masking Configuration

Masking detects signals that **hide the real problem**.

### Retry Masking

```yaml
masking:
  retries:
    multiplier: 2.0             # 2x normal retry rate
    absolute_threshold: 10.0    # Or >10 retries/sec
```

**Philosophy:**
- Retries can mask underlying failures
- Request succeeds eventually, but latency is terrible
- High retry rate indicates downstream instability

**Tuning advice:**
- Use `multiplier` if you have baseline data
- Use `absolute_threshold` for absolute limits
- Can use both together

### Queue Masking

```yaml
masking:
  queues:
    depth_trend: increasing     # Queue is growing
    saturation_pct: 85.0        # Queue 85% full
    growth_rate_pct: 10.0       # Growing 10%/minute
```

**Philosophy:**
- Growing queues hide latency from end users
- Requests wait in queue before processing
- Eventually leads to timeouts

**Tuning advice:**
- Requires knowledge of your queue capacity
- `depth_trend: increasing` is simplest
- Add `growth_rate_pct` for early detection

### Connection Masking

```yaml
masking:
  connections:
    pool_saturation: 90.0           # 90% connections in use
    wait_time_increase_pct: 50.0    # Wait time up 50%
```

**Philosophy:**
- Exhausted connection pools cause queueing
- Low CPU but high latency indicates pool exhaustion
- Common with database connections

**Tuning advice:**
- Set based on your connection pool size
- 90% is a good default threshold
- Add `wait_time_increase_pct` if you track wait times

## Confidence Configuration

Controls how confident the detector must be before triggering.

```yaml
confidence:
  # Minimum signals required
  min_signals: 3
  
  # Signal type weights
  weights:
    latency: 2.0        # Latency is most important
    masking: 1.5        # Masking is strong signal
    illusions: 1.0      # Illusions confirm
    throughput: 1.0     # Throughput is moderate
```

**How it works:**
1. Each detected signal has a severity (0.0-1.0)
2. Severity is multiplied by weight for that signal type
3. Total weighted score determines confidence

**Confidence levels:**
- **CRITICAL** (0.8-1.0): Very high confidence, all signals present
- **HIGH** (0.6-0.8): High confidence, strong signals
- **MEDIUM** (0.4-0.6): Moderate confidence, some signals
- **LOW** (0.0-0.4): Low confidence, weak signals

**Tuning advice:**
- Start with `min_signals: 3` to avoid false positives
- Increase `latency` weight if latency is your primary concern
- Decrease `min_signals` to 2 for more sensitive detection

## Custom Metric Queries

Override default PromQL queries for your specific metrics.

```yaml
metric_queries:
  # Latency from histogram
  latency_p95: >
    histogram_quantile(0.95,
      rate(http_request_duration_seconds_bucket{
        job="my-service",
        route!~"/health|/metrics"
      }[5m]))
  
  # Error rate
  error_rate: >
    sum(rate(http_requests_total{
      job="my-service",
      status=~"5.."
    }[5m]))
    / sum(rate(http_requests_total{
      job="my-service"
    }[5m])) * 100
  
  # Custom retry metric
  retry_rate: >
    sum(rate(my_custom_retry_counter{
      job="my-service"
    }[5m]))
```

**Required metrics:**
- `latency_p95` or `latency_p99`: Essential for detection
- `error_rate`: Essential for illusion detection
- `cpu_usage` or `memory_usage`: Recommended for illusion detection

**Optional metrics:**
- `latency_p50`: For tail divergence detection
- `request_rate`: For throughput symptoms
- `retry_rate`: For retry masking detection
- `queue_depth`: For queue masking detection
- `connection_pool_usage`: For connection masking detection

## Tuning Guide

### Step 1: Start Conservative

```yaml
symptoms:
  latency:
    p95_increase_pct: 50    # High threshold
    
confidence:
  min_signals: 4            # Require many signals
```

### Step 2: Run in Dry-Run Mode

```bash
python src/main.py --config config/policy.yaml --dry-run
```

Observe:
- How often it triggers
- What signals it detects
- False positive rate

### Step 3: Gradually Tighten

Lower thresholds incrementally:

```yaml
symptoms:
  latency:
    p95_increase_pct: 40    # Lower threshold
    
confidence:
  min_signals: 3            # Fewer signals needed
```

### Step 4: Tune for Your Service

Different services need different configs:

**API Gateway:**
```yaml
symptoms:
  latency:
    p95_increase_pct: 25    # Tight latency requirements
masking:
  retries:
    multiplier: 1.5         # Low retry tolerance
```

**Background Worker:**
```yaml
symptoms:
  throughput:
    queue_depth_max: 10000  # Can queue more
  latency:
    p95_increase_pct: 100   # Latency less critical
```

**Database Service:**
```yaml
masking:
  connections:
    pool_saturation: 85     # Connection pool critical
illusions:
  resources:
    io_wait_below: 20       # Track IO wait
```

### Step 5: Monitor False Positives

If you get too many false positives:

1. **Increase** `min_signals`
2. **Increase** symptom thresholds
3. **Add** more specific metric queries
4. **Adjust** baseline window (longer = more stable)

If you miss real incidents:

1. **Decrease** `min_signals`
2. **Decrease** symptom thresholds
3. **Increase** signal weights for important types
4. **Shorten** `sustained_for` duration

## Time Windows

```yaml
lookback_window: 15m    # Current metrics window
baseline_window: 1h     # Baseline calculation window
```

**Tuning advice:**
- `lookback_window`: Recent behavior (5-15 minutes)
- `baseline_window`: Normal behavior (1-4 hours)
- Longer baseline = more stable but slower to adapt
- Shorter baseline = faster adaptation but more sensitive

## Example Configurations

### High-Traffic API

```yaml
service: api-gateway
symptoms:
  latency:
    p95_increase_pct: 30
    p99_increase_pct: 50
masking:
  retries:
    multiplier: 1.8
  connections:
    pool_saturation: 85
confidence:
  min_signals: 3
  weights:
    latency: 2.5
    masking: 2.0
```

### Background Processing

```yaml
service: worker-service
symptoms:
  throughput:
    queue_depth_max: 5000
  latency:
    p95_increase_pct: 100
masking:
  queues:
    saturation_pct: 90
confidence:
  min_signals: 2
  weights:
    throughput: 2.0
```

### Database Service

```yaml
service: postgres-proxy
symptoms:
  latency:
    p95_increase_pct: 40
masking:
  connections:
    pool_saturation: 80
illusions:
  resources:
    cpu_below: 50
    io_wait_below: 15
confidence:
  min_signals: 3
```

## Validation

Test your configuration:

```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config/policy.yaml'))"

# Test with dry-run
python src/main.py --config config/policy.yaml --dry-run

# Check against recent data
python src/main.py --config config/policy.yaml
```

## Best Practices

1. **Version control your configs**: Track changes to thresholds
2. **Document tuning decisions**: Why you chose each threshold
3. **Test before deploying**: Use dry-run mode
4. **Start conservative**: Better to miss some than false alarm
5. **Tune per-service**: Different services have different normals
6. **Review periodically**: As your service evolves, so should thresholds

## Troubleshooting

**Problem**: Too many false positives

**Solution**:
- Increase `confidence.min_signals`
- Raise symptom thresholds
- Lengthen `sustained_for`

**Problem**: Missing real incidents

**Solution**:
- Decrease `confidence.min_signals`
- Lower symptom thresholds
- Add more masking signal types

**Problem**: No detections ever

**Solution**:
- Check Prometheus connectivity
- Verify metric queries return data
- Lower all thresholds temporarily
- Check logs for errors

**Problem**: Detections but wrong signals

**Solution**:
- Adjust signal weights
- Add/remove illusion types
- Tune baseline window
- Review metric queries
