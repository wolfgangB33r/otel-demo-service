# OTel Demo Service

A demo service instrumented with OpenTelemetry

## Requirements

* pip install opentelemetry-api
* pip install opentelemetry-sdk
* pip install opentelemetry-exporter-otlp-proto-http
* pip install opentelemetry-instrumentation-wsgi

## Start in a terminal

* set dt.otel.endpoint=https://<YOUR_TENANT>.live.dynatrace.com/api/v2/otlp/v1/traces
* set dt.otel.api.key=<YOUR_KEY>
* set demo.latency.ms=1000
* set service.name=demoservice
* python3 oteltest.py & disown


https://lynn.zone/blog/opting-out-of-tracing-on-gcp/