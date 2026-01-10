from fastapi import FastAPI, Request, Response
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

app = FastAPI()

RECEIVED_TRACES = []


@app.post("/v1/traces")
async def receive_traces(request: Request):
    body = await request.body()

    otlp_request = ExportTraceServiceRequest()
    otlp_request.ParseFromString(body)

    data = MessageToDict(otlp_request)
    RECEIVED_TRACES.append(data)

    # Optional: store to disk
    with open("./traces.jsonl", "a") as f:
        f.write(str(data) + "\n")

    # OTLP requires 200 OK with empty body
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4318)
