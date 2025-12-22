"""Continuous OTEL trace demo that sends traces to Dynatrace.

Reads `DT_OTEL_ENDPOINT` and `DT_OTEL_API_KEY` from the environment.
Run with: python scenarios/service-tree.py

Simulates a small service tree:
- service-web (root)
  - service-api
    - service-auth
    - service-cache
    - service-db

Each service uses its own TracerProvider/resource but shares the same OTLP endpoint.
Requires packages listed in `requirements.txt`.

The OTEL resource attributes simulates a Kubernetes environment.

The spans are linked together to form a single trace for each web request and should be of kind SERVER.
"""
import os
import time
import random
import signal
import sys
import logging
from dotenv import load_dotenv
import uuid

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes


load_dotenv()

DT_OTEL_ENDPOINT = os.getenv("DT_OTEL_ENDPOINT")
DT_OTEL_API_KEY = os.getenv("DT_OTEL_API_KEY")

logging.basicConfig(level=logging.INFO)
logging.getLogger("opentelemetry").setLevel(logging.DEBUG)

print("DT_OTEL_ENDPOINT:", DT_OTEL_ENDPOINT)
print("DT_OTEL_API_KEY set:", bool(DT_OTEL_API_KEY))

if not DT_OTEL_ENDPOINT or not DT_OTEL_API_KEY:
    print("Environment variables DT_OTEL_ENDPOINT and DT_OTEL_API_KEY must be set.")
    sys.exit(1)

# shared exporter factory
def make_exporter():
    return OTLPSpanExporter(
        endpoint=DT_OTEL_ENDPOINT,
        headers={"Authorization": f"Api-Token {DT_OTEL_API_KEY}"},
    )

# create tracer provider + tracer for a logical service name
_providers = []
_processors = []


def make_tracer_for_service(service_name):
    # generate simulated Kubernetes-like resource attributes for each service instance
    instance_id = str(uuid.uuid4())
    pod_suffix = random.randint(1, 1000)
    node_id = random.randint(1, 50)

    resource_attrs = {
        ResourceAttributes.SERVICE_NAME: service_name,
        "service.version": "0.1.0",
        "service.instance.id": instance_id,
        "k8s.cluster.name": "demo-cluster",
        "k8s.namespace.name": "demo-namespace",
        "k8s.deployment.name": f"{service_name}-deploy",
        "k8s.pod.name": f"{service_name}-pod-{pod_suffix}",
        "container.name": service_name,
        "host.name": f"node-{node_id}",
    }

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)
    exporter = make_exporter()
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    _providers.append(provider)
    _processors.append(processor)
    tracer = provider.get_tracer(service_name)
    return tracer


# create tracers for each simulated service
tracer_web = make_tracer_for_service("service-web")
tracer_api = make_tracer_for_service("service-api")
tracer_auth = make_tracer_for_service("service-auth")
tracer_cache = make_tracer_for_service("service-cache")
tracer_db = make_tracer_for_service("service-db")

running = True


def _shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# simulation functions: accept parent context to preserve trace linkage
def simulate_db(parent_ctx):
    with tracer_db.start_as_current_span("db.query", context=parent_ctx, kind=SpanKind.SERVER) as span:
        span.set_attribute("db.statement", "SELECT * FROM items WHERE id=?")
        time.sleep(random.uniform(0.01, 0.08))


def simulate_cache(parent_ctx):
    with tracer_cache.start_as_current_span("cache.lookup", context=parent_ctx, kind=SpanKind.SERVER) as span:
        hit = random.random() < 0.6
        span.set_attribute("cache.hit", hit)
        time.sleep(random.uniform(0.005, 0.02))
        if not hit:
            # miss triggers a db call within same trace
            simulate_db(trace.set_span_in_context(span))


def simulate_auth(parent_ctx):
    with tracer_auth.start_as_current_span("auth.validate", context=parent_ctx, kind=SpanKind.SERVER) as span:
        ok = random.random() < 0.95
        span.set_attribute("auth.ok", ok)
        time.sleep(random.uniform(0.002, 0.01))


def simulate_api(parent_ctx):
    with tracer_api.start_as_current_span("api.handle", context=parent_ctx, kind=SpanKind.SERVER) as span:
        span.set_attribute("http.route", "/items")
        # call auth and cache in sequence to simulate downstream services
        simulate_auth(trace.set_span_in_context(span))
        simulate_cache(trace.set_span_in_context(span))
        # sometimes perform a heavier DB operation
        if random.random() < 0.2:
            simulate_db(trace.set_span_in_context(span))
        time.sleep(random.uniform(0.005, 0.05))


def simulate_web_request(request_id):
    with tracer_web.start_as_current_span("web.request", kind=SpanKind.SERVER) as span:
        span.set_attribute("http.method", "GET")
        span.set_attribute("request.id", request_id)
        # simulate network latency, then call API
        time.sleep(random.uniform(0.005, 0.03))
        simulate_api(trace.set_span_in_context(span))


def main():
    i = 0
    print("Starting service-tree simulation. Press Ctrl+C to stop.")
    try:
        while running:
            i += 1
            simulate_web_request(i)
            if i % 10 == 0:
                print(f"Simulated {i} requests")
            # pacing between incoming requests
            time.sleep(random.uniform(0.05, 0.5))
    finally:
        print("Shutting down: flushing exporters and providers...")
        # force flush processors, then shutdown providers
        for proc in _processors:
            try:
                proc.force_flush()
            except Exception:
                pass
        for prov in _providers:
            try:
                prov.shutdown()
            except Exception:
                pass
        print("Shutdown complete.")


if __name__ == "__main__":
    main()

