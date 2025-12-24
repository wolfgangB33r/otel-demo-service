# OTel Demo Service

A comprehensive OpenTelemetry demonstration service that simulates realistic microservices architectures and generates distributed traces for monitoring and observability platforms like Dynatrace.

## How to configure

General OpenTelemetry ingest endpoint ingest information needs to be set as environment variables:
- DT_OTEL_ENDPOINT: e.g.: https://{your-environment-id}.live.dynatrace.com/api/v2/otlp/v1/traces
- DT_OTEL_API_KEY 

## Features

- **Multiple Demo Scenarios**: Pre-built scenario scripts simulating different microservices patterns
  - `single.py` — Simple single-service trace generation
  - `service-tree.py` — Multi-tier service dependency tree
  - `astroshop.py` — Complete Astronomy Shop microservices architecture (10+ services)

- **Web Dashboard** — Interactive Flask-based UI on port 8080 to:
  - Start/stop scenarios as subprocesses
  - Toggle problem patterns in real-time
  - Monitor running scenarios and their PIDs
  - View live trace generation status

- **Problem Pattern Injection** — Simulate real-world issues without code changes:
  - Slow responses and high latency
  - Service errors and timeouts
  - Memory leaks and resource exhaustion
  - Network delays

- **OpenTelemetry Integration** — Generates standard OTLP/HTTP traces with:
  - gRPC service calls with realistic attributes
  - Kubernetes resource metadata
  - Database and cache operations
  - HTTP request/response spans

## Requirements

Python 3.8+ and the following packages (see `requirements.txt`):

```bash
pip install -r [requirements.txt](http://_vscodecontentref_/0)
```

