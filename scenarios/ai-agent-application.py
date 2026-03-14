"""Continuous OTEL trace demo for an autonomous shopfront AI agent application.

Reads `DT_OTEL_ENDPOINT` and `DT_OTEL_API_KEY` from the environment.
Run with: python scenarios/ai-agent-application.py

Simulates a LangGraph and LangChain driven RAG architecture where an AI agent
buys and sells goods on behalf of a user across multiple backend services.
The generated traces include key GenAI observability attributes such as model
selection, provider metadata, token counts, cache hits, tool calls, and
guardrail decisions.
"""
import logging
import os
import random
import signal
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.schedule_utils import get_active_patterns, get_rpm as get_control_rpm

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import SpanKind


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


CONTROL_FILE = Path(".scenario_control_ai-agent-application.json")
AVAILABLE_PATTERNS = [
    "slow_vector_search",
    "llm_rate_limit",
    "tool_failures",
    "guardrail_blocks",
    "stale_inventory_cache",
    "checkout_latency",
]

AGENT_NAME = "shopfront-autonomy-agent"
GRAPH_NAME = "shopfront-autonomy-graph"
LANGGRAPH_VERSION = "0.2.35"
LANGCHAIN_VERSION = "0.3.21"
LLM_PROVIDER = "openai"
PLANNER_MODEL = "gpt-4.1-mini-2026-02-01"
SUMMARY_MODEL = "gpt-4.1-nano-2026-02-01"
EMBEDDING_MODEL = "text-embedding-3-large-2026-01-15"

USER_PROFILES = [
    {"user_id": "user-001", "region": "eu-central", "risk_tier": "standard"},
    {"user_id": "user-002", "region": "us-east", "risk_tier": "trusted"},
    {"user_id": "user-003", "region": "ap-southeast", "risk_tier": "reviewed"},
]

BUY_INTENTS = [
    {"intent": "buy", "product": "collector keyboard", "quantity": 1, "budget": 420},
    {"intent": "buy", "product": "vintage camera lens", "quantity": 1, "budget": 950},
    {"intent": "buy", "product": "portable espresso kit", "quantity": 2, "budget": 310},
]

SELL_INTENTS = [
    {"intent": "sell", "product": "retro synth module", "quantity": 1, "target_price": 680},
    {"intent": "sell", "product": "handmade leather satchel", "quantity": 3, "target_price": 220},
    {"intent": "sell", "product": "limited poster print", "quantity": 5, "target_price": 75},
]

_providers = []
_processors = []
running = True


def load_patterns():
    return get_active_patterns(CONTROL_FILE, AVAILABLE_PATTERNS)


def get_rpm():
    return get_control_rpm(CONTROL_FILE)


def make_exporter():
    return OTLPSpanExporter(
        endpoint=DT_OTEL_ENDPOINT,
        headers={"Authorization": f"Api-Token {DT_OTEL_API_KEY}"},
    )


def make_tracer_for_service(service_name, service_version):
    pod_suffix = random.randint(100, 999)
    node_id = random.randint(1, 25)
    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: service_name,
            "service.version": service_version,
            "service.instance.id": str(uuid.uuid4())[:12],
            "deployment.environment.name": "demo",
            "k8s.cluster.name": "ai-agent-demo-cluster",
            "k8s.namespace.name": "commerce-agents",
            "k8s.deployment.name": service_name,
            "k8s.pod.name": f"{service_name}-{pod_suffix}",
            "container.name": service_name,
            "host.name": f"ai-node-{node_id}",
            "langgraph.version": LANGGRAPH_VERSION,
            "langchain.version": LANGCHAIN_VERSION,
        }
    )
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(make_exporter())
    provider.add_span_processor(processor)
    _providers.append(provider)
    _processors.append(processor)
    return provider.get_tracer(service_name)


tracer_gateway = make_tracer_for_service("shopfront-gateway", "1.4.0")
tracer_agent_api = make_tracer_for_service("shopfront-agent-api", "1.4.0")
tracer_langgraph = make_tracer_for_service("langgraph-runtime", "0.2.35")
tracer_langchain = make_tracer_for_service("langchain-orchestrator", "0.3.21")
tracer_retrieval = make_tracer_for_service("rag-retrieval-service", "1.2.1")
tracer_vector_db = make_tracer_for_service("vector-store-qdrant", "1.11.0")
tracer_guardrails = make_tracer_for_service("policy-guardrails", "2.1.0")
tracer_cache = make_tracer_for_service("agent-session-cache", "7.2.0")
tracer_tools = make_tracer_for_service("agent-tool-executor", "1.1.3")
tracer_inventory = make_tracer_for_service("inventory-service", "2.6.0")
tracer_pricing = make_tracer_for_service("pricing-service", "2.9.0")
tracer_marketplace = make_tracer_for_service("marketplace-service", "3.2.0")
tracer_order = make_tracer_for_service("order-service", "2.4.0")
tracer_payment = make_tracer_for_service("payment-ledger", "2.0.4")
tracer_notification = make_tracer_for_service("notification-service", "1.8.2")


def _shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def set_attributes(span, attributes):
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def set_llm_attributes(span, operation_name, model_name, input_tokens, output_tokens, temperature, cache_hit, finish_reason="stop"):
    total_tokens = input_tokens + output_tokens
    set_attributes(
        span,
        {
            "gen_ai.system": LLM_PROVIDER,
            "gen_ai.provider.name": LLM_PROVIDER,
            "gen_ai.operation.name": operation_name,
            "gen_ai.agent.name": AGENT_NAME,
            "gen_ai.request.model": model_name,
            "gen_ai.response.model": model_name,
            "gen_ai.request.temperature": round(temperature, 2),
            "gen_ai.request.max_tokens": 768,
            "gen_ai.response.finish_reason": finish_reason,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.total_tokens": total_tokens,
            "gen_ai.cache.hit": cache_hit,
            "langgraph.graph.name": GRAPH_NAME,
            "langchain.framework": "langchain",
        },
    )


def choose_trade_intent():
    profile = random.choice(USER_PROFILES)
    intent = random.choice(BUY_INTENTS + SELL_INTENTS).copy()
    intent["user_id"] = profile["user_id"]
    intent["region"] = profile["region"]
    intent["risk_tier"] = profile["risk_tier"]
    intent["session_id"] = uuid.uuid4().hex[:16]
    return intent


def simulate_session_cache(parent_ctx, intent):
    patterns = load_patterns()
    with tracer_cache.start_as_current_span("redis.session_lookup", context=parent_ctx, kind=SpanKind.CLIENT) as span:
        stale = patterns.get("stale_inventory_cache") and random.random() < 0.45
        cache_hit = True if stale else random.random() < 0.72
        set_attributes(
            span,
            {
                "db.system": "redis",
                "db.operation": "GET",
                "db.redis.database_index": 0,
                "gen_ai.operation.name": "memory",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.cache.hit": cache_hit,
                "session.id": intent["session_id"],
                "user.id": intent["user_id"],
                "inventory.cache.stale": stale,
            },
        )
        time.sleep(random.uniform(0.002, 0.008) + (0.04 if stale else 0.0))
        return cache_hit, stale


def simulate_vector_search(parent_ctx, intent, cache_hit):
    patterns = load_patterns()
    with tracer_retrieval.start_as_current_span("rag.retrieve_context", context=parent_ctx, kind=SpanKind.INTERNAL) as retrieval_span:
        set_attributes(
            retrieval_span,
            {
                "gen_ai.operation.name": "retrieve",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.provider.name": LLM_PROVIDER,
                "gen_ai.request.model": EMBEDDING_MODEL,
                "gen_ai.embedding.dimensions": 3072,
                "gen_ai.cache.hit": cache_hit,
                "rag.corpus.name": "shopfront-policies-and-market-data",
                "shop.intent": intent["intent"],
            },
        )

        with tracer_vector_db.start_as_current_span("qdrant.search", context=trace.set_span_in_context(retrieval_span), kind=SpanKind.CLIENT) as vector_span:
            documents = random.randint(4, 9)
            top_score = round(random.uniform(0.78, 0.98), 3)
            latency = random.uniform(0.01, 0.04)
            if patterns.get("slow_vector_search"):
                latency += random.uniform(0.35, 0.9)
                vector_span.set_attribute("pattern.slow_vector_search", True)
            set_attributes(
                vector_span,
                {
                    "db.system": "qdrant",
                    "db.operation": "search",
                    "gen_ai.operation.name": "retrieve",
                    "gen_ai.agent.name": AGENT_NAME,
                    "gen_ai.embedding.model": EMBEDDING_MODEL,
                    "gen_ai.rag.documents_retrieved": documents,
                    "gen_ai.rag.top_score": top_score,
                    "gen_ai.cache.hit": cache_hit,
                    "vector.collection": "shopfront_memory",
                },
            )
            time.sleep(latency)
        retrieval_span.set_attribute("gen_ai.rag.documents_retrieved", documents)
        retrieval_span.set_attribute("gen_ai.rag.top_score", top_score)
        return documents, top_score


def simulate_guardrail_check(parent_ctx, intent, stage):
    patterns = load_patterns()
    with tracer_guardrails.start_as_current_span(f"guardrail.{stage}", context=parent_ctx, kind=SpanKind.INTERNAL) as span:
        blocked = False
        reason = "allowed"
        if patterns.get("guardrail_blocks") and random.random() < 0.35:
            blocked = True
            reason = "policy_threshold_exceeded"
        elif intent["intent"] == "buy" and intent.get("budget", 0) > 900 and random.random() < 0.08:
            blocked = True
            reason = "high_value_purchase_review"
        set_attributes(
            span,
            {
                "gen_ai.operation.name": "guardrail",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.guardrail.hit": blocked,
                "gen_ai.guardrail.name": "commerce-risk-policy",
                "gen_ai.guardrail.reason": reason,
                "shop.intent": intent["intent"],
                "user.id": intent["user_id"],
                "user.risk_tier": intent["risk_tier"],
            },
        )
        if blocked:
            span.set_attribute("error", True)
        time.sleep(random.uniform(0.003, 0.012))
        return blocked, reason


def simulate_llm_planner(parent_ctx, intent, documents, cache_hit):
    patterns = load_patterns()
    with tracer_langchain.start_as_current_span("langchain.plan_trade", context=parent_ctx, kind=SpanKind.INTERNAL) as span:
        input_tokens = random.randint(1400, 2400)
        output_tokens = random.randint(180, 420)
        temperature = random.uniform(0.1, 0.4)
        retry_count = 0
        latency = random.uniform(0.08, 0.22)

        if patterns.get("llm_rate_limit") and random.random() < 0.25:
            retry_count = 1
            latency += random.uniform(0.4, 0.8)
            span.add_event("model.rate_limit_retry", {"retry.count": retry_count, "retry.backoff_ms": 600})
            span.set_attribute("pattern.llm_rate_limit", True)

        set_llm_attributes(span, "chat", PLANNER_MODEL, input_tokens, output_tokens, temperature, cache_hit)
        set_attributes(
            span,
            {
                "langgraph.graph.name": GRAPH_NAME,
                "langgraph.node.name": "planner",
                "langchain.chain.name": "rag-trade-planner",
                "gen_ai.prompt.template": "shopfront_trade_planner_v3",
                "gen_ai.rag.documents_retrieved": documents,
                "shop.intent": intent["intent"],
                "retry.count": retry_count,
            },
        )
        time.sleep(latency)

        if intent["intent"] == "buy":
            return ["pricing.lookup", "inventory.reserve", "order.submit", "payment.capture", "notification.send"]
        return ["pricing.estimate", "marketplace.create_listing", "payment.quote_payout", "notification.send"]


def simulate_pricing_tool(parent_ctx, intent, action):
    with tracer_tools.start_as_current_span(f"tool.{action}", context=parent_ctx, kind=SpanKind.INTERNAL) as tool_span:
        tool_call_id = uuid.uuid4().hex[:12]
        set_attributes(
            tool_span,
            {
                "gen_ai.operation.name": "tool",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.tool.name": action,
                "gen_ai.tool.call.id": tool_call_id,
                "shop.product": intent["product"],
                "shop.intent": intent["intent"],
            },
        )
        with tracer_pricing.start_as_current_span("pricing.quote", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as backend_span:
            quoted_price = round(random.uniform(0.8, 1.15) * intent.get("budget", intent.get("target_price", 100)), 2)
            set_attributes(
                backend_span,
                {
                    "rpc.system": "grpc",
                    "rpc.service": "pricing.v1.PricingService",
                    "rpc.method": "Quote",
                    "price.quoted": quoted_price,
                    "currency": "USD",
                },
            )
            time.sleep(random.uniform(0.01, 0.04))
            return quoted_price, tool_call_id


def simulate_inventory_tool(parent_ctx, intent, stale_cache):
    patterns = load_patterns()
    with tracer_tools.start_as_current_span("tool.inventory.reserve", context=parent_ctx, kind=SpanKind.INTERNAL) as tool_span:
        tool_call_id = uuid.uuid4().hex[:12]
        set_attributes(
            tool_span,
            {
                "gen_ai.operation.name": "tool",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.tool.name": "inventory.reserve",
                "gen_ai.tool.call.id": tool_call_id,
                "gen_ai.cache.hit": stale_cache,
                "shop.product": intent["product"],
                "shop.quantity": intent["quantity"],
            },
        )
        with tracer_inventory.start_as_current_span("inventory.reserve", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as backend_span:
            available = random.randint(0, 8)
            if stale_cache:
                available = max(0, available - 2)
            set_attributes(
                backend_span,
                {
                    "rpc.system": "grpc",
                    "rpc.service": "inventory.v1.InventoryService",
                    "rpc.method": "Reserve",
                    "inventory.available_units": available,
                    "inventory.cache.stale": stale_cache,
                },
            )
            if patterns.get("tool_failures") and random.random() < 0.15:
                backend_span.set_attribute("error", True)
                backend_span.set_attribute("error.type", "inventory_lock_timeout")
            time.sleep(random.uniform(0.015, 0.05) + (0.05 if stale_cache else 0.0))
            return available > 0, tool_call_id


def simulate_checkout_tool(parent_ctx, intent, quoted_price):
    patterns = load_patterns()
    with tracer_tools.start_as_current_span("tool.order.submit", context=parent_ctx, kind=SpanKind.INTERNAL) as tool_span:
        tool_call_id = uuid.uuid4().hex[:12]
        set_attributes(
            tool_span,
            {
                "gen_ai.operation.name": "tool",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.tool.name": "order.submit",
                "gen_ai.tool.call.id": tool_call_id,
                "order.amount": quoted_price,
                "currency": "USD",
            },
        )
        with tracer_order.start_as_current_span("orders.create", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as order_span:
            set_attributes(
                order_span,
                {
                    "http.request.method": "POST",
                    "http.route": "/internal/orders",
                    "order.amount": quoted_price,
                    "currency": "USD",
                },
            )
            latency = random.uniform(0.02, 0.06)
            if patterns.get("checkout_latency"):
                latency += random.uniform(0.3, 0.7)
                order_span.set_attribute("pattern.checkout_latency", True)
            time.sleep(latency)

        with tracer_payment.start_as_current_span("payments.capture", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as payment_span:
            set_attributes(
                payment_span,
                {
                    "rpc.system": "grpc",
                    "rpc.service": "payments.v1.PaymentLedger",
                    "rpc.method": "Capture",
                    "payment.amount": quoted_price,
                    "payment.currency": "USD",
                },
            )
            if patterns.get("tool_failures") and random.random() < 0.12:
                payment_span.set_attribute("error", True)
                payment_span.set_attribute("error.type", "payment_processor_unavailable")
            time.sleep(random.uniform(0.015, 0.05) + (0.2 if patterns.get("checkout_latency") else 0.0))
        return tool_call_id


def simulate_marketplace_listing_tool(parent_ctx, intent, quoted_price):
    patterns = load_patterns()
    with tracer_tools.start_as_current_span("tool.marketplace.create_listing", context=parent_ctx, kind=SpanKind.INTERNAL) as tool_span:
        tool_call_id = uuid.uuid4().hex[:12]
        set_attributes(
            tool_span,
            {
                "gen_ai.operation.name": "tool",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.tool.name": "marketplace.create_listing",
                "gen_ai.tool.call.id": tool_call_id,
                "listing.target_price": quoted_price,
                "shop.product": intent["product"],
            },
        )
        with tracer_marketplace.start_as_current_span("marketplace.create_listing", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as listing_span:
            set_attributes(
                listing_span,
                {
                    "http.request.method": "POST",
                    "http.route": "/internal/listings",
                    "listing.target_price": quoted_price,
                    "listing.quantity": intent["quantity"],
                },
            )
            if patterns.get("tool_failures") and random.random() < 0.14:
                listing_span.set_attribute("error", True)
                listing_span.set_attribute("error.type", "listing_validation_error")
            time.sleep(random.uniform(0.015, 0.05))
        return tool_call_id


def simulate_notification_tool(parent_ctx, intent, outcome):
    with tracer_tools.start_as_current_span("tool.notification.send", context=parent_ctx, kind=SpanKind.INTERNAL) as tool_span:
        tool_call_id = uuid.uuid4().hex[:12]
        set_attributes(
            tool_span,
            {
                "gen_ai.operation.name": "tool",
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.tool.name": "notification.send",
                "gen_ai.tool.call.id": tool_call_id,
                "notification.channel": "email",
            },
        )
        with tracer_notification.start_as_current_span("notifications.dispatch", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as notify_span:
            set_attributes(
                notify_span,
                {
                    "messaging.system": "kafka",
                    "messaging.destination.name": "shopfront-agent-events",
                    "shop.intent": intent["intent"],
                    "shop.outcome": outcome,
                },
            )
            time.sleep(random.uniform(0.004, 0.02))
        return tool_call_id


def simulate_trade_summary(parent_ctx, intent, tool_count, cache_hit, outcome):
    with tracer_langchain.start_as_current_span("langchain.summarize_trade", context=parent_ctx, kind=SpanKind.INTERNAL) as span:
        input_tokens = random.randint(700, 1200)
        output_tokens = random.randint(120, 260)
        temperature = random.uniform(0.0, 0.2)
        set_llm_attributes(span, "chat", SUMMARY_MODEL, input_tokens, output_tokens, temperature, cache_hit)
        set_attributes(
            span,
            {
                "langgraph.node.name": "result_summarizer",
                "langchain.chain.name": "trade-summary-chain",
                "shop.intent": intent["intent"],
                "shop.outcome": outcome,
                "gen_ai.tools.count": tool_count,
            },
        )
        time.sleep(random.uniform(0.04, 0.12))


def simulate_trade_request(request_id):
    intent = choose_trade_intent()
    patterns = load_patterns()

    with tracer_gateway.start_as_current_span("shopfront.agent_request", kind=SpanKind.SERVER) as gateway_span:
        set_attributes(
            gateway_span,
            {
                "http.request.method": "POST",
                "http.route": "/api/agent/trade",
                "enduser.id": intent["user_id"],
                "user.region": intent["region"],
                "shop.intent": intent["intent"],
                "shop.product": intent["product"],
                "request.id": request_id,
                "session.id": intent["session_id"],
                "gen_ai.agent.name": AGENT_NAME,
                "gen_ai.operation.name": "agent.run",
                "langgraph.graph.name": GRAPH_NAME,
            },
        )

        with tracer_agent_api.start_as_current_span("agent_api.handle_trade", context=trace.set_span_in_context(gateway_span), kind=SpanKind.SERVER) as api_span:
            set_attributes(
                api_span,
                {
                    "rpc.system": "http",
                    "rpc.service": "shopfront.agent.api",
                    "shop.intent": intent["intent"],
                    "shop.product": intent["product"],
                },
            )

            blocked, reason = simulate_guardrail_check(trace.set_span_in_context(api_span), intent, "pre_execution")
            cache_hit, stale_cache = simulate_session_cache(trace.set_span_in_context(api_span), intent)
            documents, top_score = simulate_vector_search(trace.set_span_in_context(api_span), intent, cache_hit)

            with tracer_langgraph.start_as_current_span("langgraph.execute_workflow", context=trace.set_span_in_context(api_span), kind=SpanKind.INTERNAL) as graph_span:
                set_attributes(
                    graph_span,
                    {
                        "gen_ai.agent.name": AGENT_NAME,
                        "gen_ai.operation.name": "workflow",
                        "langgraph.graph.name": GRAPH_NAME,
                        "langgraph.node.name": "orchestrator",
                        "langchain.framework": "langchain",
                        "shop.intent": intent["intent"],
                        "shop.product": intent["product"],
                        "gen_ai.rag.documents_retrieved": documents,
                        "gen_ai.rag.top_score": top_score,
                    },
                )

                if blocked:
                    graph_span.set_attribute("shop.outcome", "blocked")
                    graph_span.set_attribute("gen_ai.guardrail.hit", True)
                    simulate_trade_summary(trace.set_span_in_context(graph_span), intent, 0, cache_hit, f"blocked:{reason}")
                    return

                tool_plan = simulate_llm_planner(trace.set_span_in_context(graph_span), intent, documents, cache_hit)
                tool_calls = []
                outcome = "completed"

                quoted_price, tool_call_id = simulate_pricing_tool(trace.set_span_in_context(graph_span), intent, tool_plan[0])
                tool_calls.append(tool_call_id)

                if intent["intent"] == "buy":
                    inventory_ok, tool_call_id = simulate_inventory_tool(trace.set_span_in_context(graph_span), intent, stale_cache)
                    tool_calls.append(tool_call_id)
                    if inventory_ok:
                        tool_calls.append(simulate_checkout_tool(trace.set_span_in_context(graph_span), intent, quoted_price))
                    else:
                        outcome = "inventory_unavailable"
                else:
                    tool_calls.append(simulate_marketplace_listing_tool(trace.set_span_in_context(graph_span), intent, quoted_price))
                    with tracer_tools.start_as_current_span("tool.payment.quote_payout", context=trace.set_span_in_context(graph_span), kind=SpanKind.INTERNAL) as tool_span:
                        tool_call_id = uuid.uuid4().hex[:12]
                        set_attributes(
                            tool_span,
                            {
                                "gen_ai.operation.name": "tool",
                                "gen_ai.agent.name": AGENT_NAME,
                                "gen_ai.tool.name": "payment.quote_payout",
                                "gen_ai.tool.call.id": tool_call_id,
                                "payment.payout_amount": quoted_price,
                            },
                        )
                        with tracer_payment.start_as_current_span("payments.quote_payout", context=trace.set_span_in_context(tool_span), kind=SpanKind.SERVER) as payment_span:
                            set_attributes(
                                payment_span,
                                {
                                    "rpc.system": "grpc",
                                    "rpc.service": "payments.v1.PaymentLedger",
                                    "rpc.method": "QuotePayout",
                                    "payment.payout_amount": quoted_price,
                                },
                            )
                            time.sleep(random.uniform(0.01, 0.04))
                        tool_calls.append(tool_call_id)

                blocked, reason = simulate_guardrail_check(trace.set_span_in_context(graph_span), intent, "post_execution")
                if blocked:
                    outcome = f"post_guardrail_block:{reason}"

                tool_calls.append(simulate_notification_tool(trace.set_span_in_context(graph_span), intent, outcome))
                graph_span.set_attribute("gen_ai.tools.count", len(tool_calls))
                graph_span.set_attribute("shop.outcome", outcome)
                graph_span.set_attribute("gen_ai.guardrail.hit", blocked)
                graph_span.set_attribute("pattern.tool_failures", patterns.get("tool_failures", False))
                simulate_trade_summary(trace.set_span_in_context(graph_span), intent, len(tool_calls), cache_hit, outcome)


def main():
    iteration = 0
    print("Starting AI agent application simulation. Press Ctrl+C to stop.")
    try:
        while running:
            try:
                iteration += 1
                simulate_trade_request(iteration)
                if iteration % 5 == 0:
                    patterns = load_patterns()
                    rpm = get_rpm()
                    print(f"Simulated {iteration} AI agent trade sessions. Active patterns: {list(patterns.keys())} | RPM: {rpm}")
                time.sleep(60.0 / get_rpm())
            except Exception as exc:
                logging.exception(f"Error during AI agent simulation loop: {exc}")
    finally:
        print("Shutting down AI agent simulation and flushing spans...")
        for processor in _processors:
            try:
                processor.force_flush()
            except Exception:
                pass
        for provider in _providers:
            try:
                provider.shutdown()
            except Exception:
                pass
        print("Shutdown complete.")


if __name__ == "__main__":
    main()