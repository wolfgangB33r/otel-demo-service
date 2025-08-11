from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.instrumentation.requests import RequestsInstrumentor

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
DEMO_LATENCY_MS = os.environ.get('DEMO_LATENCY_MS')
DEMO_CALLS = os.environ.get('DEMO_CALLS')
CALLS_TO = []
if DEMO_CALLS:
    CALLS_TO = DEMO_CALLS.split(' ')

print(CALLS_TO)

print(SERVICE_NAME)

resource = Resource(attributes={
    "service.name": SERVICE_NAME
})

trace.set_tracer_provider(TracerProvider(resource=resource))

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
        with trace.get_tracer(__name__).start_as_current_span("doSomeWork", context=extract(self.headers), kind=trace.SpanKind.SERVER):
            with trace.get_tracer(__name__).start_as_current_span("work"):
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
                    response = requests.get(url)
                    call_result = f"\nCalled: {url} Response status code: {response.status_code}"
                    self.wfile.write(call_result.encode('utf-8', errors='ignore'))




s = http.server.HTTPServer( ('', 8080), Handler )
s.serve_forever()
