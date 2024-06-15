from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
import http.server
import json
import time
import os

# Get some environment variables
DT_OTEL_ENDPOINT = os.environ.get('dt.otel.endpoint')
DT_OTEL_API_KEY = os.environ.get('dt.otel.api.key')
SERVICE_NAME = os.environ.get('service.name')

#print(DT_OTEL_ENDPOINT)
#print(DT_OTEL_API_KEY)
print(SERVICE_NAME)

resource = Resource(attributes={
    "service.name": SERVICE_NAME
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

otlp_exporter = OTLPSpanExporter(
    endpoint=DT_OTEL_ENDPOINT,
    headers={"Authorization" : "Api-Token " + DT_OTEL_API_KEY},
)

span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Hello, world!')

class Handler(http.server.SimpleHTTPRequestHandler) :
    def do_GET(self) :
        with tracer.start_as_current_span("doSomeWork", context=extract(self.headers), kind=trace.SpanKind.SERVER):
            with tracer.start_as_current_span("work", context=extract(self.headers), kind=trace.SpanKind.SERVER):
                # Read the demo latency
                DEMO_LATENCY_MS = os.environ.get('demo.latency.ms')
                latency = 0.1
                if DEMO_LATENCY_MS:
                    latency = int(DEMO_LATENCY_MS) / 1000.0
                time.sleep(latency)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Hello, world!')

s = http.server.HTTPServer( ('', 8080), Handler )
s.serve_forever()
