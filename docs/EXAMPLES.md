# Example Scenarios

Real-world examples of green-but-dead conditions and how the detector identifies them.

## Scenario 1: Database Connection Pool Exhaustion

### The Situation

Your checkout API suddenly slows down, but all monitoring looks fine:
- ✓ Error rate: 0.2% (normal)
- ✓ CPU usage: 35% (plenty of headroom)
- ✓ Memory usage: 60% (normal)
- ✗ Users complaining about slow checkouts

### What's Really Happening

```
Request → API Server → [WAIT] → Database Connection → Query
                         ↑
                    Pool full!
```

All connection pool slots are taken by slow queries. New requests wait for a connection, causing latency. Eventually some timeout and retry, which succeeds, so errors stay low.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • p95 latency increased by 78%
  • p99 latency increased by 145%

Why alerts didn't fire:
  • Error rate stable at 0.2%
  • CPU usage steady at ~35%

Masking signals detected:
  • Connection pool saturation at 95%
  • Retry rate increased 3.2× baseline

Likely impact:
  • Users experiencing slowness without visible errors
  • Connection pool exhaustion leading to request timeouts

Suggested actions:
  1. Review connection pool sizing and configuration
  2. Check for connection leaks or long-running transactions
  3. Check downstream dependency latency and response times
```

### Configuration Used

```yaml
symptoms:
  latency:
    p95_increase_pct: 30
    p99_increase_pct: 50

illusions:
  availability:
    error_rate_below: 1.0
  resources:
    cpu_below: 60.0

masking:
  connections:
    pool_saturation: 90.0
  retries:
    multiplier: 2.0
```

---

## Scenario 2: Downstream Dependency Degradation

### The Situation

Your service calls a third-party payment API that starts responding slowly:
- ✓ Your service: 0 errors
- ✓ Your service: normal CPU/memory
- ✗ Payment API: p99 went from 50ms → 2s
- ✗ Users see long checkout times

### What's Really Happening

```
User → Your API → Payment API (slow)
        ↓
    Retry on timeout
        ↓
    Eventually succeeds
```

Your service retries slow payment requests until they succeed. From your metrics perspective: no errors! But users wait 5-10 seconds for what should take 200ms.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • p99 latency increased by 892%
  • Tail latency divergence: 1.8s

Why alerts didn't fire:
  • Error rate stable at 0.1%
  • CPU usage at 42%

Masking signals detected:
  • Retry rate increased 5.1× baseline
  • Queue depth growing (now 847)

Likely impact:
  • Users experiencing slowness without visible errors
  • Retries masking true failure rate
  • Request queuing causing unpredictable delays

Suggested actions:
  1. Check downstream dependency latency and response times
  2. Investigate what's causing increased retry attempts
  3. Review timeout configurations and circuit breaker settings
```

### Configuration Used

```yaml
symptoms:
  latency:
    p99_increase_pct: 100
    tail_divergence_threshold: 1.0

masking:
  retries:
    multiplier: 3.0
  queues:
    depth_trend: increasing
```

---

## Scenario 3: Thread Pool Starvation

### The Situation

Your service uses a thread pool with 50 threads. A subset of requests start taking very long:
- ✓ Error rate: 0%
- ✓ CPU: 40% (threads are waiting, not computing)
- ✗ p99 latency: 30s (normal is 100ms)
- ✗ New requests queue up waiting for threads

### What's Really Happening

```
50 threads → 45 handling slow requests (stuck)
          → 5 handling new requests
          → Queue of 200 waiting requests
```

Most threads are blocked on slow operations (maybe external API, database lock, etc.). New requests can't get a thread, so they queue up.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (Critical Confidence)

Symptoms:
  • p95 latency increased by 2,400%
  • p99 latency increased by 3,800%
  • Queue depth exceeded max: 1,247

Why alerts didn't fire:
  • Error rate at 0.0%
  • CPU usage at 38%
  • Memory usage at 55%

Masking signals detected:
  • Queue saturation at 99%
  • Queue growth rate: 15%/min

Likely impact:
  • Users experiencing severe slowness
  • Reduced system throughput affecting user capacity
  • Request queuing causing unpredictable delays

Suggested actions:
  1. Check for worker/thread starvation
  2. Examine queue backlog and processing rates
  3. Review timeout configurations
```

### Configuration Used

```yaml
symptoms:
  latency:
    p95_increase_pct: 50
    p99_increase_pct: 100
  throughput:
    queue_depth_max: 1000

illusions:
  resources:
    cpu_below: 60.0

masking:
  queues:
    saturation_pct: 85.0
    growth_rate_pct: 10.0
```

---

## Scenario 4: GC Pause Storm (Low CPU Illusion)

### The Situation

Your Java service is having GC issues:
- ✓ CPU average: 50%
- ✓ Error rate: 0.3%
- ✗ p99 latency: 5s (normal is 200ms)
- ✗ GC pauses: 2s every 10 seconds

### What's Really Happening

```
Request arrives → Processing starts → GC PAUSE (2s) → Processing resumes
```

CPU is low because threads are paused during GC. But requests experience massive latency spikes. Errors are low because requests don't fail, they just take forever.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • p99 latency increased by 2,400%
  • Tail latency divergence: 4.8s

Why alerts didn't fire:
  • Error rate at 0.3%
  • CPU usage at 52%

Masking signals detected:
  • Retry rate increased 1.9× baseline

Likely impact:
  • Users experiencing severe slowness
  • Retries masking true failure rate

Suggested actions:
  1. Despite low CPU, check for IO wait or thread contention
  2. Review garbage collection metrics and pause times
  3. Check downstream dependency latency
```

### Configuration Used

```yaml
symptoms:
  latency:
    p99_increase_pct: 500
    tail_divergence_threshold: 2.0

illusions:
  resources:
    cpu_below: 60.0

masking:
  retries:
    multiplier: 1.5
```

---

## Scenario 5: Cascading Retry Storm

### The Situation

Service A calls Service B, which calls Service C. Service C starts having issues:
- Service C: 20% errors (alerts firing ✓)
- Service B: retries → 2% errors (no alerts)
- Service A: retries → 0.1% errors (no alerts)
- ✗ End users: 10-second checkout times

### What's Really Happening

```
User → Service A → [3 retries] → Service B → [5 retries] → Service C (failing)
```

Each layer retries, amplifying the problem. By the time it reaches the user-facing service, errors are masked but latency is terrible.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (Critical Confidence)

Symptoms:
  • p95 latency increased by 567%
  • p99 latency increased by 892%

Why alerts didn't fire:
  • Error rate at 0.1% (below threshold)
  • CPU usage at 45%

Masking signals detected:
  • Retry rate increased 12.5× baseline
  • Connection pool saturation at 93%
  • Queue depth growing (now 1,856)

Likely impact:
  • Users experiencing severe slowness
  • Retries masking true failure rate
  • Request queuing causing unpredictable delays
  • Connection pool exhaustion leading to timeouts

Suggested actions:
  1. Investigate what's causing increased retry attempts
  2. Check downstream dependency latency and response times
  3. Review timeout configurations and circuit breaker settings
  4. Examine queue backlog and processing rates
```

### Configuration Used

```yaml
symptoms:
  latency:
    p95_increase_pct: 100
    p99_increase_pct: 200

masking:
  retries:
    multiplier: 5.0
  connections:
    pool_saturation: 90.0
  queues:
    depth_trend: increasing
```

---

## Scenario 6: Read-Heavy Database Lock Contention

### The Situation

Your database has a long-running transaction holding locks:
- ✓ Database CPU: 30%
- ✓ Application error rate: 0%
- ✗ Query latency: some at 50ms, some at 15s
- ✗ Queries waiting on locks

### What's Really Happening

```
Transaction 1: BEGIN → Lock table → Long operation (30s)
Transaction 2: Query → WAIT for lock → WAIT → WAIT → Finally execute
```

Most queries are fast, but some wait for locks. This creates massive tail latency divergence.

### Detection Output

```
GREEN-BUT-DEAD DETECTED (High Confidence)

Symptoms:
  • Tail latency divergence: 14.2s
  • p99 latency increased by 28,000%

Why alerts didn't fire:
  • Error rate at 0.0%
  • CPU usage at 32%

Masking signals detected:
  • Connection pool saturation at 88%
  • Queue depth growing

Likely impact:
  • Users experiencing unpredictable slowness
  • Some requests fast, others timeout

Suggested actions:
  1. Check for connection leaks or long-running transactions
  2. Review database query performance and connection pools
  3. Despite low CPU, check for IO wait or thread contention
```

### Configuration Used

```yaml
symptoms:
  latency:
    tail_divergence_threshold: 5.0
    p99_increase_pct: 1000

illusions:
  resources:
    cpu_below: 60.0

masking:
  connections:
    pool_saturation: 85.0
```

---

## Common Patterns

### Pattern: Retry Masking

**Symptom**: High latency, low errors, high retries

**Root Causes**:
- Downstream service degradation
- Intermittent network issues
- Database connection timeouts
- Cache misses with slow backfill

**Detection Keys**:
- `retry_rate` multiplier high
- `error_rate` low (illusion)
- `latency` high (symptom)

### Pattern: Resource Illusion

**Symptom**: High latency, low CPU/memory

**Root Causes**:
- Thread/worker starvation
- IO wait (disk or network)
- Lock contention
- GC pauses

**Detection Keys**:
- `cpu_usage` low (illusion)
- `latency` high (symptom)
- Often no masking signals

### Pattern: Queue Backup

**Symptom**: Growing queues, increasing latency

**Root Causes**:
- Insufficient workers
- Slow processing
- Downstream throttling
- Producer faster than consumer

**Detection Keys**:
- `queue_depth` trending up
- `latency` increasing
- `throughput` may be dropping

### Pattern: Connection Exhaustion

**Symptom**: Latency spikes, pool saturated

**Root Causes**:
- Connection leaks
- Long-running queries
- Under-sized pool
- Sudden traffic spike

**Detection Keys**:
- `connection_pool_usage` high
- `latency` high
- `cpu_usage` often low

---

## Testing Scenarios

### Create Synthetic Load for Testing

```bash
# Scenario 1: High latency, low errors
# Inject artificial delay but return success
curl -X POST http://your-api/simulate \
  -d '{"latency_ms": 2000, "error_rate": 0.01}'

# Scenario 2: Connection pool exhaustion
# Run long-running queries
for i in {1..100}; do
  curl http://your-api/slow-query &
done

# Scenario 3: Retry storm
# Make downstream service slow
kubectl scale deployment slow-service --replicas=1
kubectl set resources deployment slow-service --requests=cpu=50m
```

### Verify Detection

```bash
# Wait for condition to develop
sleep 300

# Run detector
python src/main.py --config config/policy.yaml

# Should detect green-but-dead with appropriate signals
```

