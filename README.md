# OTel Demo Service

A demo service instrumented with OpenTelemetry

## Requirements

* pip install opentelemetry-api
* pip install opentelemetry-sdk
* pip install opentelemetry-exporter-otlp-proto-http
* pip install opentelemetry-instrumentation-wsgi
* pip install opentelemetry-instrumentation-requests


## Start in a terminal

* set DT_OTEL_ENDPOINT=https://<YOUR_TENANT>.live.dynatrace.com/api/v2/otlp/v1/traces
* set DT_OTEL_API_KEY=<YOUR_KEY>
* set DEMO_LATENCY_MS=300
* set SERVICE_NAME=demoservice
* set DEMO_CALLS=localhost:8090 localhost:8091
* python3 oteltest.py & disown