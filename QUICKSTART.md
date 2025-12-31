# Quick Start Guide

Get the Green-But-Dead Detector running in 10 minutes.

## What You'll Build

A detection system that catches this dangerous pattern:
```
✓ Error rate: 0.2%
✓ CPU: 40%
✗ Latency: 10x normal
✗ Users: "Everything is slow!"
```

## Prerequisites

- Python 3.9+
- Prometheus with your service metrics
- 10 minutes

## Step 1: Clone and Install (2 minutes)

```bash
# Navigate to project
cd deployment-detector

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Step 2: Configure (3 minutes)

```bash
# Copy example config
cp config/detector-policy.example.yaml config/detector-policy.yaml

# Edit for your service
vim config/detector-policy.yaml
```

**Minimal required changes:**

```yaml
# Change this to your service name
service: your-service-name

# Change this to your Prometheus URL
prometheus:
  url: http://your-prometheus:9090

# Keep defaults for first run - tune later
```

## Step 3: Test Connection (1 minute)

```bash
# Quick Prometheus connectivity test
python -c "
from src.metrics_fetcher import MetricsFetcher
from src.models import PrometheusConfig

config = PrometheusConfig(url='http://your-prometheus:9090')
fetcher = MetricsFetcher(config)
print('✓ Connected!' if fetcher.health_check() else '✗ Failed')
"
```

## Step 4: First Detection (1 minute)

```bash
# Run in dry-run mode (no alerts)
python src/main.py --config config/detector-policy.yaml --dry-run
```

**Expected output:**

```
════════════════════════════════════════════════════════════════════════════════
! Green-But-Dead Detector
Detecting performance failures when everything looks healthy
════════════════════════════════════════════════════════════════════════════════

[i]  Running in DRY RUN mode - no alerts will be sent

[Connecting to Prometheus...]
[Fetching metrics...]
[Evaluating rules...]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ HEALTHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

System operating normally

✓ System healthy
```

## Step 5: Tune Configuration (3 minutes)

If you got "HEALTHY" but expected detection, lower thresholds:

```yaml
symptoms:
  latency:
    p95_increase_pct: 20    # Lower from 30
    p99_increase_pct: 30    # Lower from 40

confidence:
  min_signals: 2            # Lower from 3
```

Run again:

```bash
python src/main.py --config config/detector-policy.yaml --dry-run
```

## What's Next?

### For Local Development

Keep running manually or create a cron:

```bash
# Add to crontab (every 5 minutes)
*/5 * * * * cd /path/to/deployment-detector && ./venv/bin/python src/main.py --config config/detector-policy.yaml
```

### For Production

Deploy to Kubernetes:

```bash
# Build Docker image
docker build -t green-but-dead-detector:latest .

# Create ConfigMap
kubectl create configmap green-but-dead-detector-config \
  --from-file=config/detector-policy.yaml \
  -n monitoring

# Deploy CronJob
kubectl apply -f k8s/cronjob.yaml
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full production setup.

## Understanding Output

### Healthy System

```
✓ HEALTHY
System operating normally
```

**Meaning**: No green-but-dead pattern detected. Either:
- System is actually healthy
- Thresholds too high (tune down)
- Missing required metrics

### Green-But-Dead Detected

```
! GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • p95 latency increased by 78%
  • p99 latency increased by 145%

Why alerts didn't fire:
  • Error rate stable at 0.2%
  • CPU usage steady at ~35%

Masking signals detected:
  • Connection pool saturation at 95%
  • Retry rate increased 3.2× baseline
```

**Meaning**: Classic green-but-dead pattern found!
- **Symptoms**: Real user pain (latency)
- **Illusions**: Metrics look healthy (low errors, normal CPU)
- **Masking**: Something hiding the problem (retries, pool exhaustion)

**Action**: Follow suggested investigation steps.

### Degraded

```
!  DEGRADED
System showing signs of degradation
```

**Meaning**: Problems detected but not "green-but-dead" pattern.
- Probably already alerting through normal channels
- Not the silent failure mode we're hunting

## Common First-Run Issues

### Issue: "Connection refused to Prometheus"

**Fix**: Update Prometheus URL in config:

```yaml
prometheus:
  url: http://correct-prometheus-url:9090
  verify_ssl: false  # If using self-signed certs
```

### Issue: "No data returned for queries"

**Fix**: Your metrics might have different names. Customize queries:

```yaml
metric_queries:
  latency_p95: >
    histogram_quantile(0.95,
      rate(your_actual_metric_name[5m]))
```

### Issue: "Always shows HEALTHY"

**Fix**: Thresholds too high. Lower them:

```yaml
symptoms:
  latency:
    p95_increase_pct: 10    # Start very sensitive
```

### Issue: "Too many false positives"

**Fix**: Thresholds too low. Raise them:

```yaml
confidence:
  min_signals: 4    # Require more confirming signals
```

## Testing with Synthetic Load

Want to trigger a detection for testing?

```bash
# Scenario 1: Simulate latency increase
# Make your service slow temporarily
curl -X POST http://your-service/admin/simulate-latency \
  -d '{"duration_seconds": 300, "added_latency_ms": 500}'

# Wait a few minutes for metrics to populate
sleep 180

# Run detector
python src/main.py --config config/detector-policy.yaml
```

## Quick Validation Checklist

Before considering this "working":

- [ ] Detector connects to Prometheus
- [ ] Queries return data
- [ ] Can detect HEALTHY state
- [ ] Thresholds are reasonable (not too sensitive/insensitive)
- [ ] Output is readable and actionable
- [ ] Team understands how to interpret results

## Learning Path

### Day 1: Setup
- ✓ Get it running locally
- ✓ Understand configuration basics
- ✓ See healthy output

### Week 1: Tuning
- Observe false positive/negative rate
- Adjust thresholds
- Customize metric queries if needed
- Document your tuning decisions

### Week 2: Integration
- Deploy to Kubernetes
- Add to monitoring workflow
- Create runbooks for detected patterns
- Train team on using output

### Month 1: Refinement
- Review all detections
- Fine-tune confidence settings
- Add service-specific rules
- Integrate with alerting

## Example Configurations

### Latency-Sensitive API

```yaml
service: api-gateway
symptoms:
  latency:
    p95_increase_pct: 20    # Tight threshold
    p99_increase_pct: 30
confidence:
  weights:
    latency: 3.0            # Latency is critical
```

### Best-Effort Background Worker

```yaml
service: background-worker
symptoms:
  latency:
    p95_increase_pct: 100   # Looser threshold
  throughput:
    queue_depth_max: 10000
confidence:
  min_signals: 2            # Less strict
```

## Getting Help

### Check Logs

```bash
# Run with debug logging
python src/main.py --config config/detector-policy.yaml --log-level DEBUG
```

### Validate Config

```bash
# Test config syntax
python -c "
from src.rule_engine import RuleEngine
policy = RuleEngine.load_policy('config/detector-policy.yaml')
print(f'✓ Config valid for {policy.service}')
"
```

### Common Questions

**Q: How often should it run?**  
A: Every 5 minutes is recommended. Adjust based on your needs.

**Q: Will it alert on every run?**  
A: No. Only when green-but-dead pattern is detected with sufficient confidence.

**Q: How do I stop false positives?**  
A: Increase `confidence.min_signals` and raise symptom thresholds.

**Q: Can it monitor multiple services?**  
A: Yes. Deploy one instance per service with separate configs.

**Q: Does it replace my existing monitoring?**  
A: No. It augments it by catching what traditional monitoring misses.

## Next Steps

1. **Read [CONFIGURATION.md](CONFIGURATION.md)** - Understand every config option
2. **Read [EXAMPLES.md](EXAMPLES.md)** - See real-world scenarios
3. **Read [DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment guide

## Quick Reference

```bash
# Run detection
python src/main.py

# Dry run (no alerts)
python src/main.py --dry-run

# Debug mode
python src/main.py --log-level DEBUG

# Custom config
python src/main.py --config /path/to/config.yaml

# Run tests
pytest tests/ -v

# Build Docker image
docker build -t green-but-dead-detector:latest .

# Deploy to Kubernetes
kubectl apply -f k8s/
```

## Success Criteria

You'll know it's working when:

1. ✓ Runs without errors
2. ✓ Connects to Prometheus
3. ✓ Returns sensible verdicts
4. ✓ False positive rate < 10%
5. ✓ Team finds output actionable

**You're ready for production when:**
- Tested for 1-2 weeks in dry-run mode
- Thresholds tuned for your service
- Team trained on interpreting output
- Runbooks created for detected scenarios
- Integration with notification system working

---

**** Goal**: Catch the silent killers that traditional monitoring misses.

**Remember**: This detects *contradictions*, not just thresholds. That's what makes it powerful.

Good luck! 
