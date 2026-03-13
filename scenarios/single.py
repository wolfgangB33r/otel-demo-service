"""Continuous OTEL trace demo that sends traces to Dynatrace.

Reads `DT_OTEL_ENDPOINT` and `DT_OTEL_API_KEY` from the environment.
Run with: python scenarios/single.py

Requires packages listed in `requirements.txt`.
"""
import os
import time
import random
import signal
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.schedule_utils import get_active_patterns, get_rpm as get_control_rpm

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes


load_dotenv()

DT_OTEL_ENDPOINT = os.getenv("DT_OTEL_ENDPOINT")
DT_OTEL_API_KEY = os.getenv("DT_OTEL_API_KEY")

# quick runtime check
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("opentelemetry").setLevel(logging.DEBUG)
print("DT_OTEL_ENDPOINT:", DT_OTEL_ENDPOINT)
print("DT_OTEL_API_KEY set:", bool(DT_OTEL_API_KEY))

if not DT_OTEL_ENDPOINT or not DT_OTEL_API_KEY:
    print("Environment variables DT_OTEL_ENDPOINT and DT_OTEL_API_KEY must be set.")
    sys.exit(1)


resource = Resource.create({ResourceAttributes.SERVICE_NAME: "sim-single-service"})

tracer_provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(
    endpoint=DT_OTEL_ENDPOINT,
    headers={"Authorization": f"Api-Token {DT_OTEL_API_KEY}"},
)
span_processor = BatchSpanProcessor(exporter)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)

tracer = trace.get_tracer(__name__)


running = True
CONTROL_FILE = Path(".scenario_control_single.json")
AVAILABLE_PATTERNS = ["slow_response", "high_latency", "error_rate", "timeout"]


def _shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def load_patterns():
    """Load active problem patterns from control file and schedules."""
    return get_active_patterns(CONTROL_FILE, AVAILABLE_PATTERNS)


def get_rpm():
    """Get requests per minute from control file."""
    return get_control_rpm(CONTROL_FILE)


def main():
    i = 0
    print("Starting OTEL demo loop. Press Ctrl+C to stop.")
    try:
        while running:
            try:
                i += 1
                patterns = load_patterns()
                rpm = get_rpm()
                
                with tracer.start_as_current_span("demo.operation") as span:
                    span.set_attribute("demo.iteration", i)
                    span.set_attribute("demo.random", random.random())
                    span.add_event("demo.event", {"iteration": i})
                    
                    # Base latency
                    latency = 1.0
                    
                    # Apply problem patterns
                    if patterns.get("slow_response"):
                        latency += random.uniform(0.5, 2.0)
                        span.set_attribute("pattern.slow_response", True)
                    
                    if patterns.get("high_latency"):
                        latency += random.uniform(1.0, 3.0)
                        span.set_attribute("pattern.high_latency", True)
                    
                    if patterns.get("timeout") and random.random() < 0.1:
                        span.set_attribute("error", True)
                        span.set_attribute("pattern.timeout", True)
                    
                    if patterns.get("error_rate") and random.random() < 0.2:
                        span.set_attribute("error", True)
                        span.set_attribute("pattern.error_rate", True)
                    
                    time.sleep(latency)

                if i % 5 == 0:
                    print(f"Sent {i} spans so far... Active patterns: {list(patterns.keys())} | RPM: {rpm}")
                
                # Calculate sleep time based on RPM
                # RPM = requests per minute, so sleep = 60 / RPM seconds
                sleep_time = 60.0 / rpm
                time.sleep(sleep_time)
            except Exception as e:
                logging.exception(f"Error during simulation loop: {e}")

    finally:
        print("Shutting down tracer provider and flushing spans...")
        try:
            # ensure processor flushes pending spans
            span_processor.force_flush()
        except Exception:
            pass
        try:
            tracer_provider.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()

