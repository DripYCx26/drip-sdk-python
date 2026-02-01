# Drip SDK (Python)

Drip is a Python SDK for **usage-based tracking and execution logging** in systems where spend is tied to computation — AI agents, APIs, batch jobs, and infra workloads.

This **Core SDK** is optimized for pilots: capture usage and run data first, add billing later.

---

## 60-Second Quickstart (Core SDK)

### 1. Install

```bash
pip install drip-sdk
```

### 2. Set your API key

```bash
export DRIP_API_KEY=sk_test_...
```

### 3. Track usage + execution

```python
from drip.core import Drip
import os

drip = Drip(api_key=os.environ["DRIP_API_KEY"])

# Verify connectivity
drip.ping()

# Record usage
drip.track_usage(
    customer_id="customer_123",
    meter="llm_tokens",
    quantity=842,
    metadata={"model": "gpt-4o-mini"}
)

# Record execution lifecycle
drip.record_run(
    customer_id="customer_123",
    workflow="research-agent",
    events=[
        {"eventType": "llm.call", "model": "gpt-4", "inputTokens": 500, "outputTokens": 1200},
        {"eventType": "tool.call", "name": "web-search", "duration": 1500},
    ],
    status="COMPLETED"
)

print("Usage + run recorded")
```

**Expected result:**
- No exceptions
- Events appear in the Drip dashboard within seconds

---

## Core Concepts

| Concept | Description |
|---------|-------------|
| `customer_id` | The entity you're attributing usage to |
| `meter` | What's being measured (tokens, calls, time, etc.) |
| `quantity` | Numeric usage value |
| `run` | A single request or job execution |

**Status values:** `PENDING` | `RUNNING` | `COMPLETED` | `FAILED`

**Event schema:** Payloads are schema-flexible. Drip stores events as structured JSON and does not enforce a fixed event taxonomy. CamelCase is accepted.

---

## Installation Options

```bash
pip install drip-sdk           # core only
pip install drip-sdk[fastapi]  # FastAPI helpers
pip install drip-sdk[flask]    # Flask helpers
pip install drip-sdk[all]      # everything
```

---

## SDK Variants

| Variant | Description |
|---------|-------------|
| **Core SDK** (recommended for pilots) | Usage tracking + execution logging only |
| **Full SDK** | Includes billing, balances, and workflows (for later stages) |

---

## Core SDK Methods

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

## Async Core SDK

```python
from drip.core import AsyncDrip

async with AsyncDrip(api_key="drip_sk_...") as client:
    await client.ping()

    await client.track_usage(
        customer_id="customer_123",
        meter="api_calls",
        quantity=1
    )

    result = await client.record_run(
        customer_id="customer_123",
        workflow="research-agent",
        events=[...],
        status="COMPLETED"
    )
```

---

## Who This Is For

- AI agents (token metering, tool calls, execution traces)
- API companies (per-request billing, endpoint attribution)
- RPC providers (multi-chain call tracking)
- Cloud/infra (compute seconds, storage, bandwidth)

---

## Full SDK (Billing, Webhooks, Integrations)

For billing, webhooks, middleware, and advanced features:

```python
from drip import Drip
```

See **[FULL_SDK.md](./FULL_SDK.md)** for complete documentation.

---

## Error Handling

```python
from drip import DripError, DripAPIError

try:
    result = client.track_usage(customer_id="customer_123", meter="api_calls", quantity=1)
except DripAPIError as e:
    print(f"API error {e.status_code}: {e.message}")
except DripError as e:
    print(f"Error: {e}")
```

---

## Requirements

- Python 3.10+
- httpx
- pydantic

## Links

- [Full SDK Documentation](./FULL_SDK.md)
- [API Documentation](https://drippay.dev/api-reference)
- [PyPI](https://pypi.org/project/drip-sdk/)

## License

MIT
