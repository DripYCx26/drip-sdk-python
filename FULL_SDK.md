# Drip SDK (Python) — Full SDK Reference

This document covers billing, webhooks, and advanced features. For usage tracking and execution logging, see the main [README](./README.md).

---

## Contents

- [Installation](#installation)
- [Billing Lifecycle](#billing-lifecycle)
- [Quick Start](#quick-start)
- [Async Support](#async-support)
- [API Reference](#api-reference)
- [Streaming Meter](#streaming-meter)
- [Framework Middleware](#framework-middleware)
- [LangChain Integration](#langchain-integration)
- [Webhooks](#webhooks)
- [Error Handling](#error-handling)
- [Gotchas](#gotchas)

---

## Installation

```bash
pip install drip-sdk[all]
```

```python
from drip import Drip

client = Drip(api_key="sk_test_...")
```

---

## Billing Lifecycle

Understanding `track_usage` vs `charge`:

| Method | What it does |
|--------|--------------|
| `track_usage()` | Logs usage to the ledger (no billing) |
| `charge()` | Converts usage into a billable charge |

**Typical flow:**

1. `track_usage()` throughout the day/request stream
2. Optionally `estimate_from_usage()` to preview cost
3. `charge()` to create billable charges
4. `get_balance()` / `list_charges()` for reconciliation
5. Webhooks for `charge.succeeded` / `charge.failed`

> Most pilots start with `track_usage()` only. Add `charge()` when you're ready to bill.

---

## Quick Start

```python
# Create a customer (at least one of external_customer_id or onchain_address required)
customer = client.create_customer(external_customer_id="user_123")

# Or with an on-chain address for on-chain billing
customer = client.create_customer(
    external_customer_id="user_123",
    onchain_address="0x1234567890abcdef..."
)

# Or an internal/non-billing customer (for tracking only)
internal = client.create_customer(
    external_customer_id="internal-team",
    is_internal=True
)

# Track usage (logs to ledger, no billing)
client.track_usage(
    customer_id=customer.id,
    meter="api_calls",
    quantity=1,
    metadata={"endpoint": "/v1/generate"}
)

# Create a billable charge
result = client.charge(
    customer_id=customer.id,
    meter="api_calls",
    quantity=1
)

print(f"Charged: {result.charge.amount_usdc} USDC")
```

### `create_customer()` Parameters

| Parameter | Type | Required | Description |
| --------- | ---- | -------- | ----------- |
| `external_customer_id` | `str` | No* | Your internal user/account ID |
| `onchain_address` | `str` | No* | Customer's Ethereum address |
| `is_internal` | `bool` | No | Mark as internal (non-billing). Default: `False` |
| `metadata` | `dict` | No | Arbitrary key-value metadata |

\*At least one of `external_customer_id` or `onchain_address` is required.

---

## Async Support

```python
from drip import AsyncDrip

async with AsyncDrip(api_key="sk_test_...") as client:
    # Create a customer first
    customer = await client.create_customer(
        external_customer_id="user_123"
    )

    # Then charge for usage
    result = await client.charge(
        customer_id=customer.id,
        meter="api_calls",
        quantity=1
    )
```

---

## API Reference

### Usage & Billing

| Method | Description |
|--------|-------------|
| `track_usage(params)` | Log usage to ledger (no billing) |
| `charge(params)` | Create a billable charge |
| `wrap_api_call(params)` | Wrap external API call with guaranteed usage recording |
| `get_balance(customer_id)` | Get balance and usage summary |
| `get_charge(charge_id)` | Get charge details |
| `list_charges(options)` | List all charges |

### Execution Logging

| Method | Description |
|--------|-------------|
| `record_run(params)` | Log complete agent run (simplified) |
| `start_run(params)` | Start execution trace |
| `emit_event(params)` | Log event within run |
| `emit_events_batch(params)` | Batch log events |
| `end_run(run_id, params)` | Complete execution trace |
| `get_run(run_id)` | Get run details |
| `get_run_timeline(run_id)` | Get execution timeline |
| `create_workflow(params)` | Create a workflow |
| `list_workflows()` | List all workflows |

### Customer Management

| Method | Description |
|--------|-------------|
| `create_customer(params)` | Create a customer |
| `get_customer(customer_id)` | Get customer details |
| `list_customers(options)` | List all customers |

### Webhooks

| Method | Description |
|--------|-------------|
| `create_webhook(params)` | Create webhook endpoint |
| `list_webhooks()` | List all webhooks |
| `get_webhook(webhook_id)` | Get webhook details |
| `delete_webhook(webhook_id)` | Delete a webhook |

### Cost Estimation

| Method | Description |
|--------|-------------|
| `estimate_from_usage(params)` | Estimate cost from usage data |
| `estimate_from_hypothetical(params)` | Estimate from hypothetical usage |

### Other

| Method | Description |
|--------|-------------|
| `checkout(params)` | Create checkout session (fiat on-ramp) |
| `list_meters()` | List available meters (returns `data`: list of `Meter` with `name`, `meter`, `unit_price_usd`, `is_active`) |
| `ping()` | Verify API connection |

---

## Streaming Meter

For LLM token streaming, accumulate usage locally and flush once:

```python
# Create a customer first
customer = client.create_customer(external_customer_id="user_123")

meter = client.create_stream_meter(
    customer_id=customer.id,
    meter="tokens",
)

# Stream from your LLM provider
for chunk in openai_stream:
    tokens = chunk.usage.completion_tokens if chunk.usage else 1
    meter.add_sync(tokens)  # Accumulates locally, no API call
    yield chunk

# Single charge at end of stream
result = meter.flush()
print(f"Charged {result.charge.amount_usdc} USDC for {result.quantity} tokens")
```

### Async Streaming

```python
async with AsyncDrip(api_key="sk_test_...") as client:
    # Create a customer first
    customer = await client.create_customer(external_customer_id="user_123")

    meter = client.create_stream_meter(
        customer_id=customer.id,
        meter="tokens",
    )

    async for chunk in openai_stream:
        await meter.add(chunk.tokens)

    result = await meter.flush_async()
```

### Stream Meter Options

```python
meter = client.create_stream_meter(
    customer_id=customer.id,
    meter="tokens",
    idempotency_key="stream_req_123",           # Prevent duplicates
    metadata={"model": "gpt-4"},                # Attach to charge
    flush_threshold=10000,                       # Auto-flush at 10k tokens
    on_add=lambda qty, total: print(f"Total: {total}"),
)
```

---

## Framework Middleware

### FastAPI

```python
from fastapi import FastAPI, Request, Depends
from drip.middleware.fastapi import DripMiddleware, get_drip_context, DripContext

app = FastAPI()

app.add_middleware(
    DripMiddleware,
    meter="api_calls",
    quantity=1,
    exclude_paths=["/health", "/docs"]
)

@app.post("/api/generate")
async def generate(request: Request):
    drip = get_drip_context(request)
    print(f"Charged: {drip.charge.charge.amount_usdc} USDC")
    return {"success": True}
```

### Per-Route Configuration

```python
from drip.middleware.fastapi import with_drip

@app.post("/api/expensive")
@with_drip(meter="tokens", quantity=lambda req: calculate_tokens(req))
async def expensive_operation(request: Request):
    drip = get_drip_context(request)
    return {"charged": drip.charge.charge.amount_usdc}
```

### Flask

```python
from flask import Flask
from drip.middleware.flask import drip_middleware, get_drip_context

app = Flask(__name__)

@app.route("/api/generate", methods=["POST"])
@drip_middleware(meter="api_calls", quantity=1)
def generate():
    drip = get_drip_context()
    return {"success": True}
```

### Customer Resolution

```python
# From header (default)
DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver="header")

# From query param
DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver="query")

# Custom resolver
def get_customer_from_jwt(request):
    token = request.headers.get("Authorization")
    return decode_jwt(token)["customer_id"]

DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver=get_customer_from_jwt)
```

---

## LangChain Integration

```python
from drip import Drip
from drip.integrations.langchain import DripCallbackHandler
from langchain_openai import ChatOpenAI

# Create a customer first
client = Drip(api_key="sk_test_...")
customer = client.create_customer(external_customer_id="user_123")

handler = DripCallbackHandler(
    api_key="sk_test_...",
    customer_id=customer.id,
    workflow="chatbot",
)

llm = ChatOpenAI(model="gpt-4", callbacks=[handler])
response = llm.invoke("Hello!")  # Automatically metered and billed
```

Built-in pricing for GPT-4, GPT-3.5, Claude 3, etc.

---

## Webhooks

```python
# Create webhook
webhook = client.create_webhook(
    url="https://yourapp.com/webhooks/drip",
    events=["charge.succeeded", "charge.failed", "customer.balance.low"],
    description="Production webhook"
)
# IMPORTANT: Store webhook.secret securely!

# Verify incoming webhook
from drip import verify_webhook_signature

is_valid = verify_webhook_signature(
    payload=request.body,
    signature=request.headers["X-Drip-Signature"],
    secret=webhook_secret
)
```

---

## Billing

```python
# Create a customer first
customer = client.create_customer(external_customer_id="user_123")

# Create a billable charge
result = client.charge(
    customer_id=customer.id,
    meter="api_calls",
    quantity=1,
)

# Get customer balance
balance = client.get_balance(customer.id)
print(f"Balance: {balance.balance_usdc} USDC")

# Query charges
charge = client.get_charge(result.charge.id)
charges = client.list_charges(customer_id=customer.id, limit=100)

# Cost estimation from actual usage
from datetime import datetime
estimate = client.estimate_from_usage(
    period_start=datetime(2024, 1, 1),
    period_end=datetime(2024, 1, 31),
    customer_id=customer.id,
)

# Cost estimation from hypothetical usage (no real data needed)
estimate = client.estimate_from_hypothetical(
    items=[
        {"usage_type": "api_calls", "quantity": 1000},
        {"usage_type": "tokens", "quantity": 50000},
    ]
)
print(f"Estimated cost: ${estimate.estimated_total_usdc} USDC")

# Wrap external API call with guaranteed usage recording
result = client.wrap_api_call(
    customer_id="customer_123",
    meter="tokens",
    call=lambda: openai.chat.completions.create(model="gpt-4", messages=messages),
    extract_usage=lambda r: r.usage.total_tokens,
)
# result.result = the API response, result.idempotency_key = dedup key

# Checkout (fiat on-ramp)
checkout = client.checkout(
    amount=5000,  # $50.00 in cents
    return_url="https://yourapp.com/success",
    customer_id=customer.id,
)
print(f"Checkout URL: {checkout.url}")
```

---

## Agent Run Tracking

### Simple (record_run)

```python
# Create a customer first
customer = client.create_customer(external_customer_id="user_123")

result = client.record_run(
    customer_id=customer.id,
    workflow="text-generation",
    events=[
        {"eventType": "prompt.received", "quantity": 100, "units": "tokens"},
        {"eventType": "completion.generated", "quantity": 500, "units": "tokens"},
    ],
    status="COMPLETED"
)

print(f"Run ID: {result.run.id}")
```

> **Event key format:** Both snake_case (`event_type`, `cost_units`) and camelCase (`eventType`, `costUnits`) keys are accepted in event dicts. The SDK normalizes to camelCase before sending to the API.

### Fine-Grained Control

```python
# Create a customer
customer = client.create_customer(external_customer_id="user_123")

# Create workflow (once)
workflow = client.create_workflow(
    name="Text Generation",
    slug="text-generation",
    product_surface="AGENT"
)

# Start run
run = client.start_run(
    customer_id=customer.id,
    workflow_id=workflow.id,
    correlation_id="trace_456"
)

# Emit events
client.emit_event(
    run_id=run.id,
    event_type="tokens.generated",
    quantity=1500,
    units="tokens"
)

# End run
result = client.end_run(run.id, status="COMPLETED")

# Get timeline
timeline = client.get_run_timeline(run.id)
print(f"Total cost: {timeline.totals.total_cost_units}")
```

### Distributed Tracing (correlation_id)

Pass a `correlation_id` to link Drip runs with your existing observability tools (OpenTelemetry, Datadog, etc.):

```python
from opentelemetry import trace

customer = client.create_customer(external_customer_id="user_123")
span = trace.get_current_span()

run = client.start_run(
    customer_id=customer.id,
    workflow_id=workflow.id,
    correlation_id=span.get_span_context().trace_id,  # OpenTelemetry trace ID
)

# Or with record_run:
client.record_run(
    customer_id=customer.id,
    workflow="research-agent",
    correlation_id="trace_abc123",
    events=[
        {"eventType": "llm.call", "quantity": 1700, "units": "tokens"},
    ],
    status="COMPLETED",
)
```

**Key points:**
- `correlation_id` is **user-supplied**, not auto-generated — you provide your own trace/request ID
- It's **optional** — skip it if you don't use distributed tracing
- Use it to cross-reference Drip billing data with traces in your APM dashboard
- Common values: OpenTelemetry `trace_id`, Datadog `trace_id`, or your own `request_id`
- Visible in the Drip dashboard timeline and available via `get_run_timeline()`

Events also accept a `correlation_id` for finer-grained linking:

```python
client.emit_event(
    run_id=run.id,
    event_type="llm.call",
    quantity=1700,
    units="tokens",
    correlation_id="span_xyz",  # Link to a specific span
)
```

---

## Error Handling

```python
from drip import (
    DripError,
    DripAPIError,
    DripAuthenticationError,
    DripPaymentRequiredError,
    DripRateLimitError,
    DripNetworkError,
)

try:
    result = client.charge(
        customer_id=customer.id,
        meter="api_calls",
        quantity=1
    )
except DripAuthenticationError:
    print("Invalid API key")
except DripPaymentRequiredError as e:
    print(f"Insufficient balance: {e.payment_request}")
except DripRateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after} seconds")
except DripNetworkError:
    print("Network error, please retry")
except DripAPIError as e:
    print(f"API error {e.status_code}: {e.message}")
```

---

## Gotchas

### Idempotency

Use idempotency keys to prevent duplicate charges on retries:

```python
result = client.charge(
    customer_id=customer.id,
    meter="api_calls",
    quantity=1,
    idempotency_key="req_abc123_step_1"
)

if result.is_duplicate:
    print("Already processed")
```

### Rate Limits

If you hit 429, back off and retry. The SDK handles this automatically with exponential backoff.

### track_usage vs charge

- `track_usage()` = logging (free, no balance impact)
- `charge()` = billing (deducts from balance)

Start with `track_usage()` during pilots. Add `charge()` when ready to bill.

### Development Mode

Skip charging in development:

```python
DripMiddleware(
    app,
    meter="api_calls",
    quantity=1,
    skip_in_development=True  # Skips when DRIP_ENV=development
)
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DRIP_API_KEY` | Your Drip API key |
| `DRIP_API_URL` | Custom API base URL (default: https://drip-app-hlunj.ondigitalocean.app/v1) |
| `DRIP_ENV` | Environment (development/production) |

---

## Requirements

- Python 3.10+
- httpx
- pydantic

## Links

- [Core SDK (README)](./README.md)
- [API Documentation](https://docs.drippay.dev)
- [GitHub](https://github.com/MichaelLevin5908/drip)
- [PyPI](https://pypi.org/project/drip-sdk/)
