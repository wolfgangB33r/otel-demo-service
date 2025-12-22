from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace import SpanKind

import http.server
import time
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Get some environment variables
DT_OTEL_ENDPOINT = os.environ.get('DT_OTEL_ENDPOINT')
DT_OTEL_API_KEY = os.environ.get('DT_OTEL_API_KEY')
SERVICE_NAME = os.environ.get('SERVICE_NAME')
if SERVICE_NAME is None:
    SERVICE_NAME = "demo-service"
DEMO_LATENCY_MS = os.environ.get('DEMO_LATENCY_MS')
if DEMO_LATENCY_MS is None:
    DEMO_LATENCY_MS = 0
DEMO_CALLS = os.environ.get('DEMO_CALLS')
if DEMO_CALLS is None:
    DEMO_CALLS = ""
PORT = os.environ.get('PORT')
if PORT is None:
    PORT = 8080
else:
    PORT = int(PORT)
CALLS_TO = []
if DEMO_CALLS:
    CALLS_TO = DEMO_CALLS.split(' ')

print(CALLS_TO)

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

# Instrument the requests library to propagate trace context
RequestsInstrumentor().instrument()


class Handler(http.server.SimpleHTTPRequestHandler) :

    def extract_headers(self):
        headers_string = ""
        for header, value in self.headers.items():
            headers_string += f"{header}: {value}\n"
        return headers_string

    def do_GET(self) :
        # Extract the context from incoming headers
        context = TraceContextTextMapPropagator().extract(self.headers)
        
        # Start a new span for the incoming request
        with tracer.start_as_current_span("workmethod", context=context, kind=SpanKind.SERVER) as server_span:
            server_span.set_attribute("http.method", "GET")
            server_span.set_attribute("http.url", self.path)
            server_span.set_attribute("http.client_ip", self.client_address[0])
            # Write response as text of headers
            self.send_response(200)
            self.end_headers()
            headers_string = self.extract_headers()
            self.wfile.write(headers_string.encode('utf-8', errors='ignore'))

            # Read a demo latency
            if DEMO_LATENCY_MS:
                latency = int(DEMO_LATENCY_MS) / 1000.0
                time.sleep(latency)
                self.wfile.write(f"\nDemo service latency: {latency}".encode('utf-8', errors='ignore'))
                
            for url in CALLS_TO:
                with tracer.start_as_current_span("workmethod", kind=SpanKind.CLIENT) as client_span:
                    client_span.set_attribute("http.method", "GET")
                    client_span.set_attribute("http.url", url)
                    response = requests.get(url)
                    call_result = f"\nCalled: {url} Response status code: {response.status_code}"
                    self.wfile.write(call_result.encode('utf-8', errors='ignore'))


s = http.server.HTTPServer( ('', PORT), Handler )
s.serve_forever()
