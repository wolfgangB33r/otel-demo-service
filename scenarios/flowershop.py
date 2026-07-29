"""Continuous OTEL trace demo simulating a regional FlowerShop chain.

Reads `DT_OTEL_ENDPOINT` and `DT_OTEL_API_KEY` from the environment.
Run with: python scenarios/flowershop.py

Simulates a FlowerShop chain with multiple regional store locations,
each running local Point of Sale (POS) devices that handle in-store
checkouts and credit card payments:

- sim-flowershop-pos (POS terminals, tagged per store/device)
  - sim-flowershop-store-controller (regional store coordination)
    - sim-flowershop-inventory (central inventory lookup)
  - sim-flowershop-payment-gateway (payment routing)
    - sim-flowershop-cc-processor-visa (Visa card processor)
    - sim-flowershop-cc-processor-mastercard (Mastercard processor)
  - sim-flowershop-receipt-service (local receipt printing)
  - sim-flowershop-loyalty (loyalty points, occasional)

Stores: downtown, westside, northgate, airport
Problem patterns: payment_provider_failure, pos_connectivity_loss,
                  inventory_sync_delay, receipt_printer_jam, loyalty_service_timeout
"""
import os
import time
import random
import signal
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
import uuid

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.schedule_utils import get_active_patterns, get_rpm as get_control_rpm

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
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


CONTROL_FILE = ROOT_DIR / "scenario-states" / ".scenario_control_flowershop.json"
AVAILABLE_PATTERNS = [
    "payment_provider_failure",
    "pos_connectivity_loss",
    "inventory_sync_delay",
    "receipt_printer_jam",
    "loyalty_service_timeout",
]

STORES = [
    {"name": "downtown", "region": "us-east", "city": "New York"},
    {"name": "westside", "region": "us-west", "city": "Los Angeles"},
    {"name": "northgate", "region": "us-central", "city": "Chicago"},
    {"name": "airport", "region": "us-east", "city": "New York"},
]

CARD_PROVIDERS = ["visa", "mastercard", "amex"]
FLOWER_ITEMS = [
    ("Rose Bouquet", 24.99),
    ("Sunflower Bundle", 18.50),
    ("Tulip Arrangement", 32.00),
    ("Mixed Wildflowers", 15.99),
    ("Orchid Plant", 45.00),
    ("Lily Bouquet", 28.75),
    ("Peony Bundle", 39.99),
    ("Daisy Arrangement", 12.50),
]


def load_patterns():
    return get_active_patterns(CONTROL_FILE, AVAILABLE_PATTERNS)


def get_rpm():
    return get_control_rpm(CONTROL_FILE)


_providers = []
_processors = []


def make_tracer_for_service(service_name, service_version="1.0.0", extra_attrs=None):
    instance_id = str(uuid.uuid4())[:12]
    pod_suffix = random.randint(1, 50)
    node_id = random.randint(1, 8)

    resource_attrs = {
        ResourceAttributes.SERVICE_NAME: service_name,
        "service.version": service_version,
        "service.instance.id": instance_id,
        "k8s.cluster.name": "flowershop-prod",
        "k8s.namespace.name": "retail",
        "k8s.deployment.name": service_name,
        "k8s.pod.name": f"{service_name}-{pod_suffix}",
        "k8s.pod.uid": str(uuid.uuid4()),
        "container.name": service_name,
        "container.id": str(uuid.uuid4())[:12],
        "host.name": f"retail-node-{node_id}",
        "os.type": "linux",
    }
    if extra_attrs:
        resource_attrs.update(extra_attrs)

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)
    exporter = make_exporter()
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    _providers.append(provider)
    _processors.append(processor)
    return provider.get_tracer(service_name)


tracer_pos = make_tracer_for_service("sim-flowershop-pos", "2.1.0")
tracer_store_ctrl = make_tracer_for_service("sim-flowershop-store-controller", "1.4.0")
tracer_inventory = make_tracer_for_service("sim-flowershop-inventory", "1.2.0")
tracer_payment_gw = make_tracer_for_service("sim-flowershop-payment-gateway", "3.0.1")
tracer_cc_visa = make_tracer_for_service("sim-flowershop-cc-processor-visa", "1.0.0")
tracer_cc_mc = make_tracer_for_service("sim-flowershop-cc-processor-mastercard", "1.0.0")
tracer_receipt = make_tracer_for_service("sim-flowershop-receipt-service", "1.1.0")
tracer_loyalty = make_tracer_for_service("sim-flowershop-loyalty", "2.0.0")

running = True


def _shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def simulate_inventory_lookup(parent_ctx, item_name):
    with tracer_inventory.start_as_current_span(
        "inventory.check_stock", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", "SELECT")
        span.set_attribute("db.statement", "SELECT quantity FROM stock WHERE item_name = ?")
        span.set_attribute("inventory.item", item_name)
        patterns = load_patterns()

        base_time = random.uniform(0.01, 0.04)
        in_stock = True

        if patterns.get("inventory_sync_delay"):
            base_time += random.uniform(0.8, 2.5)
            span.set_attribute("pattern.inventory_sync_delay", True)

        quantity = random.randint(0, 50)
        in_stock = quantity > 0
        span.set_attribute("inventory.quantity", quantity)
        span.set_attribute("inventory.in_stock", in_stock)
        time.sleep(base_time)
        return in_stock


def simulate_store_controller(parent_ctx, store, item_name):
    with tracer_store_ctrl.start_as_current_span(
        "store.validate_checkout", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("store.name", store["name"])
        span.set_attribute("store.region", store["region"])
        span.set_attribute("store.city", store["city"])
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/api/checkout/validate")

        in_stock = simulate_inventory_lookup(trace.set_span_in_context(span), item_name)
        span.set_attribute("checkout.item_available", in_stock)
        time.sleep(random.uniform(0.005, 0.02))
        return in_stock


def simulate_visa_processor(parent_ctx, amount):
    with tracer_cc_visa.start_as_current_span(
        "visa.charge", context=parent_ctx, kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("payment.provider", "visa")
        span.set_attribute("payment.amount", amount)
        span.set_attribute("payment.currency", "USD")
        span.set_attribute("net.peer.name", "api.visa.com")
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.url", "https://api.visa.com/v1/payments/charge")
        patterns = load_patterns()

        if patterns.get("payment_provider_failure") and random.random() < 0.6:
            span.set_attribute("http.status_code", 503)
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Visa payment processor unavailable")
            span.set_attribute("pattern.payment_provider_failure", True)
            span.set_status(StatusCode.ERROR, "Visa processor returned 503")
            time.sleep(random.uniform(0.8, 3.0))
            return False

        span.set_attribute("http.status_code", 200)
        span.set_attribute("payment.authorization_code", f"AUTH-{random.randint(100000, 999999)}")
        time.sleep(random.uniform(0.1, 0.25))
        return True


def simulate_mastercard_processor(parent_ctx, amount):
    with tracer_cc_mc.start_as_current_span(
        "mastercard.charge", context=parent_ctx, kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("payment.provider", "mastercard")
        span.set_attribute("payment.amount", amount)
        span.set_attribute("payment.currency", "USD")
        span.set_attribute("net.peer.name", "api.mastercard.com")
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.url", "https://api.mastercard.com/v1/payments/charge")
        patterns = load_patterns()

        if patterns.get("payment_provider_failure") and random.random() < 0.4:
            error_type = random.choice(["timeout", "declined", "gateway_error"])
            span.set_attribute("http.status_code", 504 if error_type == "timeout" else 402)
            span.set_attribute("error", True)
            span.set_attribute("error.type", error_type)
            span.set_attribute("error.message", f"Mastercard processor {error_type}")
            span.set_attribute("pattern.payment_provider_failure", True)
            span.set_status(StatusCode.ERROR, f"Mastercard {error_type}")
            time.sleep(random.uniform(0.5, 2.5))
            return False

        span.set_attribute("http.status_code", 200)
        span.set_attribute("payment.authorization_code", f"MC-{random.randint(100000, 999999)}")
        time.sleep(random.uniform(0.08, 0.2))
        return True


def simulate_payment_gateway(parent_ctx, amount, card_provider):
    with tracer_payment_gw.start_as_current_span(
        "payment.process", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("payment.method", "credit_card")
        span.set_attribute("payment.card_provider", card_provider)
        span.set_attribute("payment.amount", amount)
        span.set_attribute("payment.currency", "USD")
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/api/payment/charge")

        ctx = trace.set_span_in_context(span)
        success = False

        if card_provider == "visa":
            success = simulate_visa_processor(ctx, amount)
        elif card_provider == "mastercard":
            success = simulate_mastercard_processor(ctx, amount)
        else:
            # AMEX routed through Mastercard network
            success = simulate_mastercard_processor(ctx, amount)

        span.set_attribute("payment.success", success)
        if not success:
            span.set_attribute("error", True)
            span.set_status(StatusCode.ERROR, "Payment processing failed")

        time.sleep(random.uniform(0.005, 0.015))
        return success


def simulate_receipt_printer(parent_ctx, store, transaction_id):
    with tracer_receipt.start_as_current_span(
        "receipt.print", context=parent_ctx, kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("receipt.store", store["name"])
        span.set_attribute("receipt.transaction_id", transaction_id)
        span.set_attribute("receipt.format", "thermal")
        span.set_attribute("device.type", "receipt_printer")
        patterns = load_patterns()

        if patterns.get("receipt_printer_jam") and random.random() < 0.2:
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Printer jam detected — paper feed error")
            span.set_attribute("pattern.receipt_printer_jam", True)
            span.set_status(StatusCode.ERROR, "Printer hardware error")
            time.sleep(random.uniform(0.05, 0.15))
            return False

        span.set_attribute("receipt.lines_printed", random.randint(12, 24))
        time.sleep(random.uniform(0.02, 0.06))
        return True


def simulate_loyalty_update(parent_ctx, customer_id, points_earned):
    with tracer_loyalty.start_as_current_span(
        "loyalty.update_points", context=parent_ctx, kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("loyalty.customer_id", customer_id)
        span.set_attribute("loyalty.points_earned", points_earned)
        span.set_attribute("http.method", "PATCH")
        span.set_attribute("http.route", "/api/loyalty/points")
        patterns = load_patterns()

        if patterns.get("loyalty_service_timeout") and random.random() < 0.35:
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Loyalty service request timed out")
            span.set_attribute("pattern.loyalty_service_timeout", True)
            span.set_status(StatusCode.ERROR, "Loyalty service timeout")
            time.sleep(random.uniform(1.5, 4.0))
            return

        span.set_attribute("http.status_code", 200)
        span.set_attribute("loyalty.total_points", random.randint(100, 5000))
        time.sleep(random.uniform(0.02, 0.06))


def simulate_pos_checkout(store, device_id):
    item_name, item_price = random.choice(FLOWER_ITEMS)
    quantity = random.randint(1, 5)
    total_amount = round(item_price * quantity, 2)
    card_provider = random.choice(CARD_PROVIDERS)
    transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
    customer_id = f"CUST-{random.randint(10000, 99999)}"
    has_loyalty_card = random.random() < 0.55

    with tracer_pos.start_as_current_span(
        "pos.checkout", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("pos.device_id", device_id)
        span.set_attribute("pos.store", store["name"])
        span.set_attribute("pos.store_region", store["region"])
        span.set_attribute("pos.store_city", store["city"])
        span.set_attribute("pos.transaction_id", transaction_id)
        span.set_attribute("pos.item_name", item_name)
        span.set_attribute("pos.item_quantity", quantity)
        span.set_attribute("pos.total_amount", total_amount)
        span.set_attribute("pos.payment_method", "credit_card")
        span.set_attribute("pos.card_provider", card_provider)
        patterns = load_patterns()

        ctx = trace.set_span_in_context(span)

        if patterns.get("pos_connectivity_loss") and random.random() < 0.12:
            span.set_attribute("error", True)
            span.set_attribute("error.message", "POS network connectivity lost")
            span.set_attribute("pattern.pos_connectivity_loss", True)
            span.set_status(StatusCode.ERROR, "Network unavailable")
            time.sleep(random.uniform(0.3, 1.0))
            return

        # Validate with store controller and check inventory
        in_stock = simulate_store_controller(ctx, store, item_name)
        if not in_stock:
            span.set_attribute("pos.checkout_result", "item_unavailable")
            time.sleep(random.uniform(0.01, 0.02))
            return

        # Process credit card payment
        payment_ok = simulate_payment_gateway(ctx, total_amount, card_provider)
        span.set_attribute("pos.payment_success", payment_ok)

        if payment_ok:
            # Print receipt
            simulate_receipt_printer(ctx, store, transaction_id)

            # Update loyalty points if customer has card
            if has_loyalty_card:
                points = int(total_amount)
                simulate_loyalty_update(ctx, customer_id, points)

            span.set_attribute("pos.checkout_result", "success")
        else:
            span.set_attribute("pos.checkout_result", "payment_failed")
            span.set_status(StatusCode.ERROR, "Payment declined")

        time.sleep(random.uniform(0.01, 0.03))


def main():
    i = 0
    print("Starting FlowerShop simulation. Press Ctrl+C to stop.")

    # POS device IDs per store (2–3 terminals per location)
    store_devices = {
        store["name"]: [f"pos-{store['name']}-{n:02d}" for n in range(1, random.randint(3, 4))]
        for store in STORES
    }

    try:
        while running:
            try:
                i += 1
                store = random.choice(STORES)
                device_id = random.choice(store_devices[store["name"]])
                simulate_pos_checkout(store, device_id)

                if i % 10 == 0:
                    patterns = load_patterns()
                    rpm = get_rpm()
                    print(
                        f"Simulated {i} checkouts. "
                        f"Active patterns: {list(patterns.keys())} | RPM: {rpm}"
                    )

                sleep_time = 60.0 / get_rpm()
                time.sleep(sleep_time)
            except Exception as e:
                logging.exception(f"Error during simulation loop: {e}")
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
