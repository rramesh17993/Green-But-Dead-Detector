# Deployment Guide

Complete guide to deploying the Green-But-Dead Detector in production.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Monitoring the Detector](#monitoring-the-detector)
- [Production Checklist](#production-checklist)

## Prerequisites

### Required
- Python 3.9 or higher
- Access to Prometheus instance
- Kubernetes cluster (for K8s deployment)

### Recommended
- Slack workspace (for notifications)
- Log aggregation system (ELK, Splunk, etc.)
- Alerting platform (PagerDuty, Opsgenie)

## Local Development

### 1. Setup Python Environment

```bash
# Clone repository
cd deployment-detector

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Detection Policy

```bash
# Copy example config
cp config/detector-policy.example.yaml config/detector-policy.yaml

# Edit configuration
vim config/detector-policy.yaml

# Key settings to update:
# - service: your-service-name
# - prometheus.url: http://your-prometheus:9090
# - Tune thresholds based on your service
```

### 3. Test Locally

```bash
# Dry run (no alerts)
python src/main.py --config config/detector-policy.yaml --dry-run

# Full run
python src/main.py --config config/detector-policy.yaml

# With debug logging
python src/main.py --config config/detector-policy.yaml --log-level DEBUG
```

### 4. Validate Configuration

```bash
# Test Prometheus connectivity
python -c "
from src.metrics_fetcher import MetricsFetcher
from src.models import PrometheusConfig
config = PrometheusConfig(url='http://prometheus:9090')
fetcher = MetricsFetcher(config)
print('Healthy!' if fetcher.health_check() else 'Failed!')
"

# Validate YAML syntax
python -c "
import yaml
from src.rule_engine import RuleEngine
policy = RuleEngine.load_policy('config/detector-policy.yaml')
print(f'Config valid for service: {policy.service}')
"
```

## Docker Deployment

### 1. Build Docker Image

```bash
# Build image
docker build -t green-but-dead-detector:latest .

# Verify image
docker images | grep green-but-dead-detector
```

### 2. Run Container

```bash
# Run with mounted config
docker run --rm \
  -v $(pwd)/config:/app/config \
  green-but-dead-detector:latest

# Run with custom Prometheus URL
docker run --rm \
  -v $(pwd)/config:/app/config \
  -e PROMETHEUS_URL=http://prometheus:9090 \
  green-but-dead-detector:latest

# Run continuously (every 5 minutes)
docker run -d \
  --name green-but-dead-detector \
  --restart unless-stopped \
  -v $(pwd)/config:/app/config \
  green-but-dead-detector:latest \
  /bin/sh -c 'while true; do python src/main.py --config /app/config/detector-policy.yaml; sleep 300; done'
```

### 3. Docker Compose (Optional)

```yaml
# docker-compose.yml
version: '3.8'

services:
  detector:
    build: .
    container_name: green-but-dead-detector
    volumes:
      - ./config:/app/config:ro
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
    command: >
      /bin/sh -c '
        while true; do
          python src/main.py --config /app/config/detector-policy.yaml
          sleep 300
        done
      '
```

```bash
# Start with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f detector

# Stop
docker-compose down
```

## Kubernetes Deployment

### 1. Prepare Configuration

```bash
# Create namespace
kubectl create namespace monitoring

# Create ConfigMap from your policy
kubectl create configmap green-but-dead-detector-config \
  --from-file=config/detector-policy.yaml \
  -n monitoring

# Or apply the provided ConfigMap
kubectl apply -f k8s/configmap.yaml
```

### 2. Deploy as CronJob (Recommended)

```bash
# Deploy CronJob
kubectl apply -f k8s/cronjob.yaml

# Verify deployment
kubectl get cronjobs -n monitoring
kubectl get pods -n monitoring -l app=green-but-dead-detector

# View logs
kubectl logs -n monitoring -l app=green-but-dead-detector --tail=100

# Manually trigger a run
kubectl create job -n monitoring \
  --from=cronjob/green-but-dead-detector \
  manual-detection-$(date +%s)
```

### 3. Deploy as Deployment (Alternative)

For continuous monitoring instead of periodic checks:

```bash
# Apply deployment manifest
kubectl apply -f k8s/deployment.yaml  # If you created one

# Or deploy inline
kubectl create deployment green-but-dead-detector \
  -n monitoring \
  --image=green-but-dead-detector:latest \
  -- /bin/sh -c 'while true; do python src/main.py --config /config/detector-policy.yaml; sleep 300; done'

# Mount ConfigMap
kubectl set volume deployment/green-but-dead-detector \
  -n monitoring \
  --add --name=config \
  --type=configmap \
  --configmap-name=green-but-dead-detector-config \
  --mount-path=/config
```

### 4. Optional: RBAC Setup

If your detector needs Kubernetes API access:

```bash
# Apply RBAC configuration
kubectl apply -f k8s/rbac.yaml

# Update CronJob to use ServiceAccount
kubectl patch cronjob green-but-dead-detector \
  -n monitoring \
  -p '{"spec":{"jobTemplate":{"spec":{"template":{"spec":{"serviceAccountName":"green-but-dead-detector"}}}}}}'
```

### 5. Secrets Management

```bash
# Create secrets (don't commit these!)
kubectl create secret generic green-but-dead-detector-secrets \
  -n monitoring \
  --from-literal=slack-webhook-url='https://hooks.slack.com/services/YOUR/WEBHOOK/URL' \
  --from-literal=prometheus-token='YOUR_TOKEN'

# Or apply from file
kubectl apply -f k8s/secrets.yaml
```

## Monitoring the Detector

### 1. View Detection Results

```bash
# Kubernetes logs
kubectl logs -n monitoring -l app=green-but-dead-detector --tail=50 -f

# Filter for detections
kubectl logs -n monitoring -l app=green-but-dead-detector | grep "GREEN-BUT-DEAD"

# View latest detection output
kubectl exec -n monitoring \
  $(kubectl get pod -n monitoring -l app=green-but-dead-detector -o name | head -1) \
  -- cat /tmp/green-but-dead-detector-latest.txt
```

### 2. Job History

```bash
# View CronJob history
kubectl get jobs -n monitoring -l app=green-but-dead-detector

# View successful runs
kubectl get jobs -n monitoring -l app=green-but-dead-detector --field-selector status.successful=1

# View failed runs
kubectl get jobs -n monitoring -l app=green-but-dead-detector --field-selector status.successful=0
```

### 3. Debugging

```bash
# Run in debug mode
kubectl create job -n monitoring debug-detection-$(date +%s) \
  --from=cronjob/green-but-dead-detector

# Override command for debugging
kubectl run -n monitoring debug-detector -it --rm \
  --image=green-but-dead-detector:latest \
  --restart=Never \
  -- python src/main.py --config /config/detector-policy.yaml --log-level DEBUG
```

## Notifications Setup

### Slack Integration

Add to your detector (modify `src/main.py`):

```python
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def send_slack_notification(verdict):
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return
    
    if verdict.state == DetectorState.GREEN_BUT_DEAD:
        payload = explainer.format_slack(verdict)
        # Send to Slack
        # ... implementation ...
```

### PagerDuty Integration

```python
import os
import requests

def send_pagerduty_alert(verdict):
    if verdict.confidence not in [ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL]:
        return
    
    integration_key = os.getenv('PAGERDUTY_KEY')
    payload = {
        "routing_key": integration_key,
        "event_action": "trigger",
        "payload": {
            "summary": verdict.summary,
            "severity": "error",
            "source": verdict.service,
            "custom_details": {
                "confidence": verdict.confidence.value,
                "signals": verdict.total_signals
            }
        }
    }
    requests.post("https://events.pagerduty.com/v2/enqueue", json=payload)
```

## Production Checklist

### Configuration
- [ ] Detection policy tuned for your service
- [ ] Prometheus URL correct
- [ ] Metric queries customized if needed
- [ ] Thresholds validated in dry-run mode
- [ ] False positive rate acceptable

### Security
- [ ] Secrets not committed to git
- [ ] Kubernetes secrets created
- [ ] RBAC properly scoped (if used)
- [ ] Container runs as non-root
- [ ] Image scanned for vulnerabilities

### Monitoring
- [ ] Logs centralized (ELK, Splunk, CloudWatch)
- [ ] Detector job failures alerted
- [ ] Detection verdicts logged
- [ ] Notification channels configured
- [ ] Runbooks prepared

### Reliability
- [ ] Resource limits set
- [ ] Job timeout configured
- [ ] Retry policy appropriate
- [ ] Concurrency controlled
- [ ] Failure handling tested

### Documentation
- [ ] Configuration documented
- [ ] Team trained on detection output
- [ ] Runbooks created for detected scenarios
- [ ] Contact info for escalation
- [ ] Tuning history tracked

## Scaling Considerations

### Multiple Services

Deploy one detector per critical service:

```bash
# Create configs for each service
for service in api-gateway checkout-service user-service; do
  kubectl create configmap green-but-dead-detector-config-$service \
    --from-file=config/policy-$service.yaml \
    -n monitoring
done

# Deploy CronJobs
for service in api-gateway checkout-service user-service; do
  kubectl apply -f k8s/cronjob-$service.yaml
done
```

### High-Frequency Monitoring

For very critical services, run more frequently:

```yaml
# cronjob.yaml
schedule: "*/2 * * * *"  # Every 2 minutes instead of 5
```

**Warning**: More frequent = more Prometheus load. Balance appropriately.

### Multi-Cluster

For multi-cluster deployments:

1. Deploy detector in each cluster
2. Or centralize with Prometheus federation
3. Tag detections with cluster ID

```yaml
# Add cluster context to config
service: api-gateway
cluster: us-west-2-prod
```

## Troubleshooting

### Detector Not Running

```bash
# Check CronJob
kubectl describe cronjob green-but-dead-detector -n monitoring

# Check recent jobs
kubectl get jobs -n monitoring -l app=green-but-dead-detector

# Check pod status
kubectl get pods -n monitoring -l app=green-but-dead-detector
```

### No Detections

```bash
# Run with debug logging
kubectl create job -n monitoring debug-$(date +%s) \
  --from=cronjob/green-but-dead-detector

# Check Prometheus connectivity
kubectl run -n monitoring test-prometheus -it --rm \
  --image=curlimages/curl \
  --restart=Never \
  -- curl http://prometheus-server/api/v1/query?query=up

# Lower thresholds temporarily for testing
```

### False Positives

- Increase `confidence.min_signals`
- Raise symptom thresholds
- Add more specific illusion checks
- Review baseline window

### Missed Detections

- Lower thresholds
- Decrease `confidence.min_signals`
- Add more masking signal types
- Shorten lookback window

## Upgrade Process

### Rolling Update

```bash
# Build new image with version tag
docker build -t green-but-dead-detector:v1.1.0 .
docker tag green-but-dead-detector:v1.1.0 green-but-dead-detector:latest

# Update Kubernetes
kubectl set image cronjob/green-but-dead-detector \
  -n monitoring \
  detector=green-but-dead-detector:v1.1.0

# Verify
kubectl describe cronjob green-but-dead-detector -n monitoring | grep Image
```

### Configuration Update

```bash
# Update ConfigMap
kubectl create configmap green-but-dead-detector-config \
  --from-file=config/detector-policy.yaml \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -

# Force new run to pick up config
kubectl create job -n monitoring \
  --from=cronjob/green-but-dead-detector \
  config-test-$(date +%s)
```

## Performance Tuning

### Prometheus Query Optimization

```yaml
# Use recording rules for expensive queries
metric_queries:
  latency_p95: service:latency:p95  # Pre-computed recording rule
```

### Resource Allocation

```yaml
# Adjust based on your metric volume
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"  # Increase if OOM
    cpu: "500m"      # Increase if slow
```

### Timeout Configuration

```yaml
# prometheus config
prometheus:
  timeout: 30  # Increase if queries timeout
```

## Backup and Recovery

```bash
# Backup configuration
kubectl get configmap -n monitoring green-but-dead-detector-config -o yaml > backup/configmap.yaml
kubectl get cronjob -n monitoring green-but-dead-detector -o yaml > backup/cronjob.yaml

# Restore
kubectl apply -f backup/
```

## Uninstall

```bash
# Remove CronJob
kubectl delete cronjob green-but-dead-detector -n monitoring

# Remove ConfigMap
kubectl delete configmap green-but-dead-detector-config -n monitoring

# Remove secrets (if used)
kubectl delete secret green-but-dead-detector-secrets -n monitoring

# Remove RBAC (if used)
kubectl delete -f k8s/rbac.yaml
```

## Next Steps

After deployment:

1. **Monitor for 1-2 weeks** in dry-run mode
2. **Tune thresholds** based on observations
3. **Enable notifications** once stable
4. **Create runbooks** for detected scenarios
5. **Train team** on detector output
6. **Iterate** on configuration

Remember: The detector is a diagnostic tool, not an alerting system. Use it to explain, not just notify.
