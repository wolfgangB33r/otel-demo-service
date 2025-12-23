"""Continuous OTEL trace demo simulating the OpenTelemetry Astronomy Shop demo.

Reads `DT_OTEL_ENDPOINT` and `DT_OTEL_API_KEY` from the environment.
Run with: python scenarios/astroshop.py

Simulates the Astronomy Shop microservices architecture:
- frontend (web UI)
  - cartservice (gRPC)
  - productcatalogservice (gRPC)
  - recommendationservice (gRPC)
    - productcatalogservice (gRPC)
  - checkoutservice (gRPC)
    - cartservice (gRPC)
    - paymentservice (gRPC)
    - shippingservice (gRPC)
    - emailservice (gRPC)
    - currencyservice (gRPC)
  - currencyservice (gRPC)
  - adservice (gRPC)

Each service has realistic Kubernetes resource attributes and generates spans
with realistic latencies and attributes for each technology.
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


def make_exporter():
    return OTLPSpanExporter(
        endpoint=DT_OTEL_ENDPOINT,
        headers={"Authorization": f"Api-Token {DT_OTEL_API_KEY}"},
    )


_providers = []
_processors = []


def make_tracer_for_service(service_name, service_version="1.0.0"):
    """Create a tracer with realistic Kubernetes-like resource attributes."""
    instance_id = str(uuid.uuid4())[:12]
    pod_suffix = random.randint(1, 100)
    node_id = random.randint(1, 10)

    resource_attrs = {
        ResourceAttributes.SERVICE_NAME: service_name,
        "service.version": service_version,
        "service.instance.id": instance_id,
        "k8s.cluster.name": "astro-demo-cluster",
        "k8s.namespace.name": "default",
        "k8s.deployment.name": service_name,
        "k8s.pod.name": f"{service_name}-{pod_suffix}",
        "k8s.pod.uid": str(uuid.uuid4()),
        "container.name": service_name,
        "container.id": str(uuid.uuid4())[:12],
        "host.name": f"worker-node-{node_id}",
        "os.type": "linux",
    }

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)
    exporter = make_exporter()
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    _providers.append(provider)
    _processors.append(processor)
    return provider.get_tracer(service_name)


# Create tracers for all Astronomy Shop services
tracer_frontend = make_tracer_for_service("frontend", "1.0.0")
tracer_cartservice = make_tracer_for_service("cartservice", "0.3.0")
tracer_productcatalog = make_tracer_for_service("productcatalogservice", "0.3.0")
tracer_recommendation = make_tracer_for_service("recommendationservice", "0.3.0")
tracer_checkout = make_tracer_for_service("checkoutservice", "0.3.0")
tracer_payment = make_tracer_for_service("paymentservice", "0.3.0")
tracer_shipping = make_tracer_for_service("shippingservice", "0.3.0")
tracer_email = make_tracer_for_service("emailservice", "0.3.0")
tracer_currency = make_tracer_for_service("currencyservice", "0.3.0")
tracer_ad = make_tracer_for_service("adservice", "0.3.0")
tracer_redis = make_tracer_for_service("redis", "7.0")

running = True


def _shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# Add problem pattern toggles at the top after imports
PROBLEM_PATTERNS = {
    "slow_productcatalog": False,  # Adds 500ms-2s latency
    "cartservice_errors": False,   # 10% error rate
    "payment_timeout": False,      # 50% timeout errors
    "high_cpu_shipping": False,    # Adds 1-3s latency
    "memory_leak_recommendation": False,  # Gradually increases latency
    "network_latency": False,      # +100-500ms on all calls
}

# Track memory leak state
_memory_leak_counter = 0


def toggle_pattern(pattern_name, enabled):
    """Toggle a problem pattern on/off at runtime."""
    if pattern_name in PROBLEM_PATTERNS:
        PROBLEM_PATTERNS[pattern_name] = enabled
        print(f"Problem pattern '{pattern_name}' set to {enabled}")
    else:
        print(f"Unknown pattern: {pattern_name}")


def print_patterns():
    """Print current pattern status."""
    print("\n=== Problem Patterns ===")
    for pattern, enabled in PROBLEM_PATTERNS.items():
        status = "ON" if enabled else "OFF"
        print(f"  {pattern}: {status}")
    print()


# Service simulation functions
def simulate_redis_operation(parent_ctx, operation):
    """Simulate Redis cache operation."""
    with tracer_redis.start_as_current_span(
        f"redis.{operation}", context=parent_ctx, kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("db.system", "redis")
        span.set_attribute("db.operation", operation)
        base_time = random.uniform(0.001, 0.005)
        
        if PROBLEM_PATTERNS["network_latency"]:
            base_time += random.uniform(0.1, 0.5)
        
        time.sleep(base_time)


def simulate_productcatalog(parent_ctx):
    """Simulate ProductCatalogService gRPC call."""
    with tracer_productcatalog.start_as_current_span(
        "ListProducts", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.ProductCatalog")
        span.set_attribute("rpc.method", "ListProducts")
        
        # Check cache first
        simulate_redis_operation(trace.set_span_in_context(span), "GET")
        
        base_time = random.uniform(0.02, 0.05)
        
        if PROBLEM_PATTERNS["slow_productcatalog"]:
            base_time += random.uniform(0.5, 2.0)
            span.set_attribute("error", "slow_response")
        
        span.set_attribute("rpc.grpc.status_code", 0)
        time.sleep(base_time)


def simulate_cartservice(parent_ctx, operation="GetCart"):
    """Simulate CartService gRPC call."""
    with tracer_cartservice.start_as_current_span(
        operation, context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.CartService")
        span.set_attribute("rpc.method", operation)
        
        # Check for cartservice errors
        if PROBLEM_PATTERNS["cartservice_errors"] and random.random() < 0.1:
            span.set_attribute("rpc.grpc.status_code", 2)  # UNKNOWN error
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Cart service unavailable")
            time.sleep(random.uniform(0.01, 0.03))
            return
        
        # Redis backend
        simulate_redis_operation(trace.set_span_in_context(span), "GET")
        span.set_attribute("rpc.grpc.status_code", 0)
        time.sleep(random.uniform(0.01, 0.03))


def simulate_currency(parent_ctx):
    """Simulate CurrencyService gRPC call."""
    with tracer_currency.start_as_current_span(
        "Convert", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.CurrencyService")
        span.set_attribute("rpc.method", "Convert")
        span.set_attribute("rpc.grpc.status_code", 0)
        span.set_attribute("currency.from", "USD")
        span.set_attribute("currency.to", random.choice(["EUR", "GBP", "JPY"]))
        time.sleep(random.uniform(0.005, 0.015))


def simulate_recommendation(parent_ctx):
    """Simulate RecommendationService gRPC call."""
    global _memory_leak_counter
    
    with tracer_recommendation.start_as_current_span(
        "ListRecommendations", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.RecommendationService")
        span.set_attribute("rpc.method", "ListRecommendations")
        span.set_attribute("rpc.grpc.status_code", 0)
        
        # Call product catalog
        simulate_productcatalog(trace.set_span_in_context(span))
        
        base_time = random.uniform(0.03, 0.08)
        
        if PROBLEM_PATTERNS["memory_leak_recommendation"]:
            _memory_leak_counter += 1
            leak_delay = (_memory_leak_counter / 1000) * 0.01  # Gradual increase
            base_time += leak_delay
            span.set_attribute("memory.leak_indicator", _memory_leak_counter)
        
        time.sleep(base_time)


def simulate_payment(parent_ctx):
    """Simulate PaymentService gRPC call."""
    with tracer_payment.start_as_current_span(
        "Charge", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.PaymentService")
        span.set_attribute("rpc.method", "Charge")
        span.set_attribute("payment.amount", round(random.uniform(10, 500), 2))
        span.set_attribute("payment.currency", "USD")
        
        if PROBLEM_PATTERNS["payment_timeout"] and random.random() < 0.5:
            span.set_attribute("rpc.grpc.status_code", 4)  # DEADLINE_EXCEEDED
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Payment timeout")
            time.sleep(random.uniform(0.5, 2.0))
            return
        
        span.set_attribute("rpc.grpc.status_code", 0)
        time.sleep(random.uniform(0.05, 0.15))


def simulate_shipping(parent_ctx):
    """Simulate ShippingService gRPC call."""
    with tracer_shipping.start_as_current_span(
        "GetQuote", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.ShippingService")
        span.set_attribute("rpc.method", "GetQuote")
        span.set_attribute("shipping.country", random.choice(["US", "DE", "JP", "UK"]))
        
        base_time = random.uniform(0.02, 0.06)
        
        if PROBLEM_PATTERNS["high_cpu_shipping"]:
            base_time += random.uniform(1.0, 3.0)
            span.set_attribute("cpu.high", True)
            span.set_attribute("error", "high_latency")
        
        span.set_attribute("rpc.grpc.status_code", 0)
        time.sleep(base_time)


def simulate_email(parent_ctx):
    """Simulate EmailService gRPC call."""
    with tracer_email.start_as_current_span(
        "SendOrderConfirmation", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.EmailService")
        span.set_attribute("rpc.method", "SendOrderConfirmation")
        span.set_attribute("rpc.grpc.status_code", 0)
        time.sleep(random.uniform(0.01, 0.03))

def simulate_checkout(parent_ctx):
    """Simulate CheckoutService orchestrating multiple services."""
    with tracer_checkout.start_as_current_span(
        "PlaceOrder", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.CheckoutService")
        span.set_attribute("rpc.method", "PlaceOrder")
        span.set_attribute("rpc.grpc.status_code", 0)

        ctx = trace.set_span_in_context(span)
        # Get cart
        simulate_cartservice(ctx, "GetCart")
        # Calculate currency
        simulate_currency(ctx)
        # Process payment
        simulate_payment(ctx)
        # Get shipping quote
        simulate_shipping(ctx)
        # Send confirmation email
        simulate_email(ctx)

        time.sleep(random.uniform(0.01, 0.02))

def simulate_ad(parent_ctx):
    """Simulate AdService gRPC call."""
    with tracer_ad.start_as_current_span(
        "GetAds", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("rpc.service", "hipster.AdService")
        span.set_attribute("rpc.method", "GetAds")
        span.set_attribute("rpc.grpc.status_code", 0)
        span.set_attribute("ad.context_keys", random.randint(1, 5))
        time.sleep(random.uniform(0.01, 0.04))


def simulate_frontend_request(request_id):
    """Simulate a complete frontend browsing session."""
    with tracer_frontend.start_as_current_span(
        "HTTP GET /", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.url", "/")
        span.set_attribute("http.status_code", 200)
        span.set_attribute("request.id", request_id)

        ctx = trace.set_span_in_context(span)

        # Typical user flow: browse products
        simulate_productcatalog(ctx)
        simulate_recommendation(ctx)

        # Sometimes add to cart
        if random.random() < 0.6:
            simulate_cartservice(ctx, "AddItem")

        # Sometimes checkout
        if random.random() < 0.3:
            simulate_checkout(ctx)

        # Load ads
        simulate_ad(ctx)

        # Convert currency if needed
        if random.random() < 0.5:
            simulate_currency(ctx)

        time.sleep(random.uniform(0.01, 0.05))


def main():
    i = 0
    print("Starting Astronomy Shop simulation. Press Ctrl+C to stop.")
    print_patterns()
    print("Type patterns to list them, or 'pattern_name=True/False' to toggle.")
    
    try:
        while running:
            i += 1
            simulate_frontend_request(i)
            if i % 10 == 0:
                print(f"Simulated {i} user sessions")
            time.sleep(random.uniform(0.2, 1.0))
    finally:
        print("Shutting down: flushing exporters and providers...")
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