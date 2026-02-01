# Drip SDK for Python

Official Python SDK for **Drip** - usage tracking and cost attribution for metered infrastructure.

## Installation

```bash
pip install drip-sdk
```

With framework support:

```bash
# FastAPI support
pip install drip-sdk[fastapi]

# Flask support
pip install drip-sdk[flask]

# All frameworks
pip install drip-sdk[all]
```

## Core SDK (Recommended for Pilots)

For most use cases, import the **Core SDK** - a simplified API focused on two concepts:

1. **Usage Tracking** - Record metered usage events
2. **Execution Logging** - Log agent runs with detailed event traces

```python
from drip.core import Drip

# Initialize the client
client = Drip(api_key="drip_sk_...")

# Verify connection
client.ping()
```

### Track Usage

```python
# Track any metered usage (no billing - just recording)
client.track_usage(
    customer_id="cus_123",
    meter="api_calls",
    quantity=1,
    metadata={"endpoint": "/v1/generate", "method": "POST"}
)
```

### Record Agent Runs

```python
# Record a complete agent execution with one call
result = client.record_run(
    customer_id="cus_123",
    workflow="research-agent",
    events=[
        {"eventType": "llm.call", "model": "gpt-4", "inputTokens": 500, "outputTokens": 1200},
        {"eventType": "tool.call", "name": "web-search", "duration": 1500},
        {"eventType": "llm.call", "model": "gpt-4", "inputTokens": 200, "outputTokens": 800},
    ],
    status="COMPLETED"
)

print(result.summary)
# Output: "Research Agent: 3 events recorded (2.5s)"
```

### Async Core SDK

```python
from drip.core import AsyncDrip

async with AsyncDrip(api_key="drip_sk_...") as client:
    await client.ping()

    await client.track_usage(
        customer_id="cus_123",
        meter="api_calls",
        quantity=1
    )

    result = await client.record_run(
        customer_id="cus_123",
        workflow="research-agent",
        events=[...],
        status="COMPLETED"
    )
```

### Core SDK Methods

| Method | Description |
|--------|-------------|
| `ping()` | Verify API connection |
| `create_customer(params)` | Create a customer |
| `get_customer(customer_id)` | Get customer details |
| `list_customers(options)` | List all customers |
| `track_usage(params)` | Record metered usage |
| `record_run(params)` | Log complete agent run (simplified) |
| `start_run(params)` | Start execution trace |
| `emit_event(params)` | Log event within run |
| `emit_events_batch(params)` | Batch log events |
| `end_run(run_id, params)` | Complete execution trace |
| `get_run_timeline(run_id)` | Get execution timeline |

---

## Full SDK

For billing, webhooks, and advanced features, use the full SDK:

```python
from drip import Drip

client = Drip(api_key="drip_sk_...")

# All Core SDK methods plus:
# - charge(), get_balance(), get_charge(), list_charges()
# - create_webhook(), list_webhooks(), delete_webhook()
# - estimate_from_usage(), estimate_from_hypothetical()
# - checkout(), and more
```

## Quick Start (Full SDK)

```python
from drip import Drip

# Initialize the client
client = Drip(api_key="drip_sk_...")

# Create a customer
customer = client.create_customer(
    onchain_address="0x1234567890abcdef...",
    external_customer_id="user_123"
)

# Create a charge
result = client.charge(
    customer_id=customer.id,
    meter="api_calls",
    quantity=1
)

print(f"Charged: {result.charge.amount_usdc} USDC")
```

## Async Support (Full SDK)

```python
from drip import AsyncDrip

async with AsyncDrip(api_key="drip_sk_...") as client:
    customer = await client.create_customer(
        onchain_address="0x1234..."
    )

    result = await client.charge(
        customer_id=customer.id,
        meter="api_calls",
        quantity=1
    )
```

## FastAPI Integration

```python
from fastapi import FastAPI, Request, Depends
from drip.middleware.fastapi import DripMiddleware, get_drip_context, DripContext

app = FastAPI()

# Apply middleware to all routes
app.add_middleware(
    DripMiddleware,
    meter="api_calls",
    quantity=1,
    exclude_paths=["/health", "/docs"]
)

@app.post("/api/generate")
async def generate(request: Request):
    drip = get_drip_context(request)
    print(f"Charged customer {drip.customer_id}: {drip.charge.charge.amount_usdc} USDC")
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

### Dependency Injection

```python
from drip.middleware.fastapi import create_drip_dependency

charge_tokens = create_drip_dependency(
    meter="tokens",
    quantity=100,
)

@app.post("/api/generate")
async def generate(drip: DripContext = Depends(charge_tokens)):
    return {"charged": drip.charge.charge.amount_usdc}
```

## Flask Integration

```python
from flask import Flask
from drip.middleware.flask import drip_middleware, get_drip_context

app = Flask(__name__)

@app.route("/api/generate", methods=["POST"])
@drip_middleware(meter="api_calls", quantity=1)
def generate():
    drip = get_drip_context()
    print(f"Charged: {drip.charge.charge.amount_usdc}")
    return {"success": True}
```

### Application-Wide Middleware

```python
from drip.middleware.flask import DripFlaskMiddleware

app = Flask(__name__)
drip = DripFlaskMiddleware(
    app,
    meter="api_calls",
    quantity=1,
    exclude_paths=["/health"]
)
```

## Customer Resolution

The middleware needs to identify which customer to charge. Configure this with `customer_resolver`:

```python
# From X-Drip-Customer-Id header (default)
DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver="header")

# From query parameter (?customer_id=xxx)
DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver="query")

# Custom resolver
def get_customer_from_jwt(request):
    token = request.headers.get("Authorization")
    return decode_jwt(token)["customer_id"]

DripMiddleware(app, meter="api_calls", quantity=1, customer_resolver=get_customer_from_jwt)
```

## Full SDK API Reference

### Customer Management

```python
# Create customer
customer = client.create_customer(
    onchain_address="0x...",
    external_customer_id="user_123",
    metadata={"plan": "pro"}
)

# Get customer
customer = client.get_customer("cus_123")

# List customers
result = client.list_customers(status=CustomerStatus.ACTIVE, limit=50)
```

### Usage Tracking (No Billing)

```python
# Track usage without creating a charge
result = client.track_usage(
    customer_id="cus_123",
    meter="api_calls",
    quantity=1,
    metadata={"endpoint": "/v1/generate"}
)
```

### Billing (Full SDK Only)

```python
# Get balance
balance = client.get_balance("cus_123")
print(f"Balance: {balance.balance_usdc} USDC")

# Create a charge
result = client.charge(
    customer_id="cus_123",
    meter="api_calls",
    quantity=1,
    idempotency_key="unique_key_123",
    metadata={"request_id": "req_456"}
)

# Check if it was a duplicate (idempotent)
if result.is_duplicate:
    print("Charge was already processed")

# Get charge details
charge = client.get_charge("chg_123")

# List charges
charges = client.list_charges(customer_id="cus_123", limit=100)
```

### Streaming Meter

For LLM token streaming and other high-frequency metering scenarios:

```python
from drip import Drip

client = Drip(api_key="drip_sk_...")

# Create a stream meter for a customer
meter = client.create_stream_meter(
    customer_id="cust_abc123",
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

#### Async Streaming

```python
async with AsyncDrip(api_key="drip_sk_...") as client:
    meter = client.create_stream_meter(
        customer_id="cust_abc123",
        meter="tokens",
    )

    async for chunk in openai_stream:
        await meter.add(chunk.tokens)  # May auto-flush if threshold set

    result = await meter.flush_async()
```

#### Stream Meter Options

```python
meter = client.create_stream_meter(
    customer_id="cust_abc123",
    meter="tokens",

    # Optional: Custom idempotency key
    idempotency_key="stream_req_123",

    # Optional: Metadata attached to the charge
    metadata={"model": "gpt-4", "endpoint": "/v1/chat"},

    # Optional: Auto-flush when threshold reached
    flush_threshold=10000,  # Flush every 10k tokens

    # Optional: Callback on each add
    on_add=lambda qty, total: print(f"Added {qty}, total: {total}"),
)
```

#### Handling Partial Failures

```python
meter = client.create_stream_meter(
    customer_id="cust_abc123",
    meter="tokens",
)

try:
    for chunk in stream:
        meter.add_sync(chunk.tokens)
        yield chunk
    meter.flush()
except Exception as error:
    # Charge for tokens delivered before failure
    if meter.total > 0:
        meter.flush()
    raise
```

### Checkout (Fiat On-Ramp)

```python
# Create checkout session
checkout = client.checkout(
    amount=5000,  # $50.00 in cents
    return_url="https://yourapp.com/success",
    customer_id="cus_123"
)

# Redirect user to checkout.url
print(f"Checkout URL: {checkout.url}")
```

### Webhooks

```python
# Create webhook
webhook = client.create_webhook(
    url="https://yourapp.com/webhooks/drip",
    events=["charge.succeeded", "customer.balance.low"],
    description="Production webhook"
)
# IMPORTANT: Store webhook.secret securely!

# Verify webhook signature
from drip import verify_webhook_signature

is_valid = verify_webhook_signature(
    payload=request.body,
    signature=request.headers["X-Drip-Signature"],
    secret=webhook_secret
)
```

### Agent Run Tracking

The simplest way to log agent runs is with `record_run()`:

```python
# Record a complete run in one call (recommended)
result = client.record_run(
    customer_id="cus_123",
    workflow="text-generation",  # Creates workflow if doesn't exist
    events=[
        {"eventType": "prompt.received", "quantity": 100, "units": "tokens"},
        {"eventType": "completion.generated", "quantity": 500, "units": "tokens"},
        {"eventType": "tool.called", "description": "web_search"},
    ],
    status="COMPLETED"
)

print(f"Run ID: {result.run.id}")
print(f"Total cost: {result.total_cost_units}")
```

### Fine-Grained Run Control (Full SDK)

For more control, use the step-by-step API:

```python
from drip import Drip

client = Drip(api_key="drip_sk_...")

# Create a workflow (only needed once)
workflow = client.create_workflow(
    name="Text Generation",
    slug="text-generation",
    product_surface="AGENT"
)

# Start a run
run = client.start_run(
    customer_id="cus_123",
    workflow_id=workflow.id,
    correlation_id="trace_456"
)

# Emit events as they happen
event = client.emit_event(
    run_id=run.id,
    event_type="tokens.generated",
    quantity=1500,
    units="tokens",
    cost_units=0.015
)

# End the run
result = client.end_run(run.id, status="COMPLETED")

# Get timeline
timeline = client.get_run_timeline(run.id)
print(f"Total cost: {timeline.totals.total_cost_units}")
```

### LangChain Integration

Auto-track token usage and tool calls with LangChain:

```python
from drip.integrations.langchain import DripCallbackHandler
from langchain_openai import ChatOpenAI

handler = DripCallbackHandler(
    api_key="drip_sk_...",
    customer_id="cust_123",
    workflow="chatbot",
)

llm = ChatOpenAI(model="gpt-4", callbacks=[handler])
response = llm.invoke("Hello!")  # Automatically metered and billed
```

Built-in pricing for popular models (GPT-4, GPT-3.5, Claude 3, etc.) with automatic cost calculation.

## Idempotency

Prevent duplicate charges with idempotency keys:

```python
# Generate deterministic key
key = Drip.generate_idempotency_key(
    customer_id="cus_123",
    step_name="process_document",
    run_id="run_456",
    sequence=1
)

# Use in charge
result = client.charge(
    customer_id="cus_123",
    meter="api_calls",
    quantity=1,
    idempotency_key=key
)

# Safe to retry - won't double charge
if result.is_duplicate:
    print("Already processed")
```

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
    result = client.charge(customer_id="cus_123", meter="api_calls", quantity=1)
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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DRIP_API_KEY` | Your Drip API key |
| `DRIP_API_URL` | Custom API base URL (default: https://api.drip.dev/v1) |
| `DRIP_ENV` | Environment (development/production) for `skip_in_development` |

## Development Mode

Skip charging in development:

```python
DripMiddleware(
    app,
    meter="api_calls",
    quantity=1,
    skip_in_development=True  # Skips charging when DRIP_ENV=development
)
```

## Requirements

- Python 3.10+
- httpx
- pydantic

## Feature Summary

| Feature | Status | Description |
|---------|--------|-------------|
| FastAPI Middleware | ✅ | `DripMiddleware` |
| Flask Decorator | ✅ | `@drip_middleware` |
| Async Support | ✅ | `AsyncDrip` client |
| Streaming Meter | ✅ | For LLM token streams |
| LangChain Integration | ✅ | `DripCallbackHandler` |
| x402 Payment Flow | ✅ | Automatic 402 handling |
| Webhook Verification | ✅ | HMAC-SHA256 |
| Idempotency | ✅ | Built-in or custom keys |
| Type Safety | ✅ | Full Pydantic models |

## License

MIT
