# Architecture Overview

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes CronJob                          │
│                     (runs every 5 minutes)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Main Orchestrator                            │
│                      (main.py)                                  │
│                                                                 │
│  1. Load Configuration (YAML)                                  │
│  2. Initialize Components                                       │
│  3. Coordinate Detection Pipeline                              │
│  4. Output Results                                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
           ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Metrics  │  │   Rule   │  │ Detector │
    │ Fetcher  │  │  Engine  │  │          │
    └──────────┘  └──────────┘  └──────────┘
           │             │             │
           │             │             │
           ▼             ▼             ▼
    ┌──────────────────────────────────────┐
    │        Detection Verdict              │
    │    (state, confidence, signals)       │
    └──────────────┬───────────────────────┘
                   │
                   ▼
            ┌─────────────┐
            │  Explainer  │
            │ (formatter) │
            └──────┬──────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
   Terminal    Logs      Slack
   Output     (JSON)  (optional)
```

## Component Interactions

### 1. Metrics Fetcher → Prometheus

```
┌──────────────────┐
│ Metrics Fetcher  │
│                  │
│ - Query builder  │
│ - Data parser    │
│ - Baseline calc  │
└────────┬─────────┘
         │
         │ PromQL Queries
         │
         ▼
┌──────────────────┐
│   Prometheus     │
│                  │
│ - Time series DB │
│ - Query engine   │
│ - Metric storage │
└──────────────────┘

Queries:
• histogram_quantile(0.95, rate(latency[5m]))
• sum(rate(http_requests_total{status=~"5.."}[5m]))
• container_cpu_usage_seconds_total
• ...
```

### 2. Rule Engine → Signals

```
┌──────────────────────────────────────────────┐
│            Rule Engine                       │
└──────────────────────────────────────────────┘
                     │
       ┌─────────────┼─────────────┐
       │             │             │
       ▼             ▼             ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Symptom  │  │ Illusion │  │ Masking  │
│  Rules   │  │  Rules   │  │  Rules   │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     ▼             ▼             ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Latency  │  │Error Rate│  │ Retries  │
│ P95 ↑ 50%│  │  < 1%    │  │  3x ↑    │
└──────────┘  └──────────┘  └──────────┘

Each rule produces: SignalDetection
  - signal_type
  - description  
  - value
  - severity (0.0-1.0)
```

### 3. Detector → Verdict

```
┌────────────────────────────────────────┐
│            Detector                    │
│                                        │
│  Input: Dict[str, List[Signal]]       │
│  {                                     │
│    'symptoms': [...]                   │
│    'illusions': [...]                  │
│    'masking_signals': [...]            │
│  }                                     │
│                                        │
│  Process:                              │
│  1. Calculate confidence score         │
│  2. Determine system state             │
│  3. Generate summary                   │
│  4. Assess impact                      │
│  5. Suggest actions                    │
│                                        │
│  Output: DetectionVerdict              │
└────────────────────────────────────────┘

Confidence Calculation:
  weighted_score = Σ(signal.severity × weight[signal.type])
  
  if symptoms AND illusions AND masking:
    weighted_score *= 1.2  # Boost for full pattern
  
  if total_signals < min_signals:
    weighted_score *= (total_signals / min_signals)
  
  confidence = min(weighted_score / 10.0, 1.0)
```

### 4. State Machine

```
                  ┌─────────────┐
                  │   UNKNOWN   │
                  └──────┬──────┘
                         │
              confidence > 0.3?
                         │
           ┌─────────────┼─────────────┐
           │                           │
          Yes                         No
           │                           │
           ▼                           ▼
  ┌────────────────┐            Stay UNKNOWN
  │   Evaluate     │
  │   Signals      │
  └────────┬───────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
symptoms?     no symptoms?
    │             │
   Yes           No
    │             │
    ▼             ▼
┌────────┐   ┌─────────┐
│illusions│   │ HEALTHY │
│masking? │   └─────────┘
└────┬────┘
     │
  ┌──┴──┐
  │     │
 Yes   No
  │     │
  ▼     ▼
GREEN  DEGRADED
-BUT-
-DEAD
```

## Data Flow Example

### Scenario: Connection Pool Exhaustion

```
Step 1: Metrics Collection
─────────────────────────
Prometheus → Metrics Fetcher
  latency_p95: 0.20s (was 0.10s)
  error_rate: 0.2%
  cpu_usage: 35%
  pool_usage: 95%
  retry_rate: 3.5/s (was 1.0/s)

Step 2: Rule Evaluation
────────────────────────
Rule Engine evaluates:

✓ Symptom: p95 latency ↑ 100%
  → SignalDetection(type="latency_p95_increase", severity=1.0)

✓ Illusion: Error rate 0.2% < 1%
  → SignalDetection(type="low_error_rate", severity=0.9)

✓ Illusion: CPU 35% < 60%
  → SignalDetection(type="low_cpu", severity=0.7)

✓ Masking: Pool 95% > 90%
  → SignalDetection(type="pool_saturation", severity=0.9)

✓ Masking: Retries 3.5× baseline
  → SignalDetection(type="retry_spike", severity=0.8)

Step 3: Confidence Calculation
───────────────────────────────
symptoms_score = 1.0 × 2.0 = 2.0
illusions_score = (0.9 + 0.7) × 1.0 = 1.6
masking_score = (0.9 + 0.8) × 1.5 = 2.55

total = 2.0 + 1.6 + 2.55 = 6.15

All three categories present → boost × 1.2 = 7.38

confidence = min(7.38 / 10.0, 1.0) = 0.738
confidence_level = HIGH

Step 4: State Determination
────────────────────────────
symptoms: ✓ (latency)
illusions: ✓ (error rate, cpu)
masking: ✓ (pool, retries)
confidence: 0.738 (high)

→ state = GREEN_BUT_DEAD

Step 5: Verdict Generation
───────────────────────────
DetectionVerdict {
  state: GREEN_BUT_DEAD
  confidence: HIGH
  summary: "p95 latency increased by 100% but system appears healthy"
  
  likely_impact: [
    "Users experiencing slowness",
    "Connection pool exhaustion leading to timeouts",
    "Retries masking true failure rate"
  ]
  
  suggested_actions: [
    "Review connection pool sizing",
    "Check for connection leaks",
    "Check downstream dependency latency"
  ]
}

Step 6: Formatting & Output
────────────────────────────
Explainer formats verdict:
  - Terminal: Colored, structured
  - Logs: JSON structured
  - Slack: Block Kit format (optional)
```

## Configuration Flow

```
┌──────────────────────────────────────────┐
│   detector-policy.yaml                   │
│                                          │
│   service: api-gateway                   │
│   symptoms:                              │
│     latency:                             │
│       p95_increase_pct: 30              │
│   illusions:                             │
│     availability:                        │
│       error_rate_below: 1.0             │
│   masking:                               │
│     retries:                             │
│       multiplier: 2.0                    │
└──────────────┬───────────────────────────┘
               │
               │ Load & Validate
               ▼
        ┌──────────────┐
        │ RuleEngine   │
        │ .load_policy │
        └──────┬───────┘
               │
               │ Parse to Pydantic models
               ▼
        ┌──────────────┐
        │DetectorPolicy│
        └──────┬───────┘
               │
               │ Inject into components
               ▼
    ┌────────────────────────┐
    │ All detector components│
    │ use same policy        │
    └────────────────────────┘
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│              Kubernetes Cluster                     │
│                                                     │
│  ┌───────────────────────────────────────────┐    │
│  │         Namespace: monitoring             │    │
│  │                                           │    │
│  │  ┌─────────────────────────────────┐     │    │
│  │  │  CronJob                        │     │    │
│  │  │  green-but-dead-detector        │     │    │
│  │  │                                 │     │    │
│  │  │  Schedule: */5 * * * *          │     │    │
│  │  │  (every 5 minutes)              │     │    │
│  │  └───────────┬─────────────────────┘     │    │
│  │              │                             │    │
│  │              │ Creates                     │    │
│  │              ▼                             │    │
│  │  ┌─────────────────────────────────┐     │    │
│  │  │  Job (detector-job-12345)       │     │    │
│  │  │                                 │     │    │
│  │  │  ┌─────────────────────┐        │     │    │
│  │  │  │ Pod                 │        │     │    │
│  │  │  │                     │        │     │    │
│  │  │  │ Container:          │        │     │    │
│  │  │  │  detector:latest    │        │     │    │
│  │  │  │                     │        │     │    │
│  │  │  │ Mounts:             │        │     │    │
│  │  │  │  /config ← ConfigMap│        │     │    │
│  │  │  └─────────────────────┘        │     │    │
│  │  └─────────────────────────────────┘     │    │
│  │                                           │    │
│  │  ┌─────────────────────────────────┐     │    │
│  │  │  ConfigMap                      │     │    │
│  │  │  detector-config                │     │    │
│  │  │                                 │     │    │
│  │  │  Data:                          │     │    │
│  │  │    detector-policy.yaml         │     │    │
│  │  └─────────────────────────────────┘     │    │
│  │                                           │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
│  ┌───────────────────────────────────────────┐    │
│  │  Service: prometheus-server               │    │
│  │  Endpoint: http://prometheus:9090         │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
└─────────────────────────────────────────────────────┘

Network Flow:
  Detector Pod → Prometheus Service
    HTTP GET /api/v1/query_range
    PromQL queries
  
  Detector Pod → Slack (optional)
    HTTP POST to webhook
    Formatted notification
```

## Error Handling

```
              ┌─────────────┐
              │    Start    │
              └──────┬──────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ Load Configuration     │
        └────────┬───────────────┘
                 │
         ┌───────┴───────┐
         │               │
      Success          Error
         │               │
         ▼               ▼
    ┌────────┐    ┌──────────┐
    │Continue│    │Log Error │
    │        │    │Exit(1)   │
    └────┬───┘    └──────────┘
         │
         ▼
┌─────────────────────┐
│Connect to Prometheus│
└────────┬────────────┘
         │
   ┌─────┴─────┐
   │           │
Success      Error
   │           │
   ▼           ▼
┌────┐   ┌──────────┐
│Cont│   │Log Error │
│    │   │Retry (3x)│
└─┬──┘   └────┬─────┘
  │           │
  │      ┌────┴────┐
  │      │         │
  │   Success    Fail
  │      │         │
  │      └────┐    │
  │           │    ▼
  │           │  Exit(1)
  │           │
  ▼◄──────────┘
┌──────────────┐
│Fetch Metrics │
└──────┬───────┘
       │
  ┌────┴────┐
  │         │
Success   Error
  │         │
  ▼         ▼
┌────┐  ┌──────────┐
│Cont│  │Use Cached│
│    │  │or Skip   │
└─┬──┘  └────┬─────┘
  │          │
  ▼◄─────────┘
┌────────────┐
│  Evaluate  │
│   Rules    │
└─────┬──────┘
      │
      ▼
┌────────────┐
│  Output    │
│  Verdict   │
└─────┬──────┘
      │
      ▼
┌────────────┐
│   Done     │
│ Exit(0-2)  │
└────────────┘

Exit Codes:
  0 = Healthy
  1 = Green-but-dead detected
  2 = Critical detection
  3 = Error
```

This architecture is designed for:
- **Safety**: Read-only, can't break production
- **Simplicity**: Clear flow, easy to debug
- **Reliability**: Error handling at each step
- **Observability**: Structured logging throughout
- **Maintainability**: Modular components, clear boundaries
