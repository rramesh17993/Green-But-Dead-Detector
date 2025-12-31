# Green-But-Dead Detector

Detects performance failures that traditional monitoring misses.

## The Problem

Systems can be "green-but-dead":
- ✓ Error rate low, CPU normal, health checks passing
- ✗ Users experience severe slowness or timeouts

Traditional monitoring watches errors and resources. It misses **performance degradation**.

## How It Works

Detects **contradictions** in system behavior:

```
IF symptoms (latency ↑, throughput ↓)
AND illusions (errors low, CPU normal)
AND masking (retries ↑, queues growing)
THEN → Green-but-dead detected
```

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure
cp config/detector-policy.example.yaml config/my-policy.yaml
# Edit my-policy.yaml with your Prometheus URL and service name

# Run
python src/main.py --config config/my-policy.yaml
```

## Example Output

```
GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • p95 latency increased 78%
  • p99 latency increased 145%

Why alerts didn't fire:
  • Error rate stable at 0.2%
  • CPU usage at 35%

Masking signals:
  • Connection pool 95% saturated
  • Retry rate 3.2x baseline

Suggested actions:
  1. Check connection pool sizing
  2. Review downstream dependencies
```

## Deployment

**Kubernetes CronJob** (runs every 5 minutes):
```bash
kubectl apply -f k8s/
```

**Docker**:
```bash
docker build -t detector .
docker run -v ./config:/app/config detector
```

## Configuration

Edit `config/detector-policy.yaml`:

```yaml
service: my-service

symptoms:
  latency:
    p95_increase_pct: 30  # Alert if p95 up 30%
    p99_increase_pct: 40  # Alert if p99 up 40%

illusions:
  availability:
    error_rate_below: 1.0  # Below 1% looks healthy

masking:
  retries:
    multiplier: 2.0  # 2x retries is suspicious
  connections:
    pool_saturation: 90.0  # 90% pool is masking
```

## Documentation

- `QUICKSTART.md` - 10-minute setup
- `docs/EXAMPLES.md` - Real-world scenarios
- `docs/CONFIGURATION.md` - Complete reference
- `docs/DEPLOYMENT.md` - Production deployment
- `docs/ARCHITECTURE.md` - System design

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## License

MIT
