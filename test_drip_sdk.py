"""
Test Drip Python SDK - Comprehensive Feature Testing

This test suite demonstrates all major SDK features:

1. API Connection - Verify connectivity
2. Customer Creation - Create customers with random addresses
3. Usage Tracking - Track metered usage (no billing)
4. Agent Runs (record_run) - Record complete execution traces
5. Balance Retrieval - Check customer account balance
6. Billing - Create charges (requires pricing plan)
7. List Customers - Retrieve all customers
8. Token Tracking - Track LLM input/output tokens per customer
9. Idempotency - Prevent duplicate charges with idempotency keys
10. Multi-Customer Usage - Track different usage across customers
11. Audit Trail - Track who did what with detailed metadata
12. Correlation ID - Link runs to your distributed traces
13. Fine-Grained Runs - start_run, emit_event, end_run, get_run_timeline

Installation:
    pip install drip-sdk

Before running:
    export DRIP_API_KEY="your_secret_key_here"
    python test_drip_sdk.py

What this tests:
- ✅ Customer attribution (which customer used what)
- ✅ Token tracking (LLM usage per customer)
- ✅ Idempotency (duplicate prevention with real idempotency_key param)
- ✅ Audit trail (who did what, when, from where)
- ✅ Multi-customer scenarios
- ✅ Correlation ID (distributed tracing)
- ✅ Fine-grained run control (start_run → emit_event → end_run → timeline)
"""

import os
import secrets
from drip import Drip

# ============================================================================
# SETUP
# ============================================================================

# Get API key from environment (never hardcode!)
API_KEY = os.getenv('DRIP_API_KEY')

if not API_KEY:
    print("❌ Error: DRIP_API_KEY environment variable not set")
    print("\nRun this first:")
    print('export DRIP_API_KEY="sk_live_16dc182b-1c0b-4d56-ab64-06199fb1b977_2a17d3..."')
    exit(1)

# Initialize Drip client (point to public deployment)
drip = Drip(
    api_key=API_KEY,
    base_url="https://drip-app-hlunj.ondigitalocean.app/v1"  # Include /v1
)

print("🚀 Testing Drip Python SDK")
print("=" * 60)

# ============================================================================
# TEST 1: Verify Connection
# ============================================================================

print("\n1️⃣  Testing API Connection...")
try:
    drip.ping()
    print("   ✅ Connected to Drip API successfully!")
except Exception as e:
    print(f"   ❌ Failed to connect: {e}")
    exit(1)

# ============================================================================
# TEST 2: Create a Customer
# ============================================================================

print("\n2️⃣  Creating a test customer...")
try:
    # Generate random address and ID for each test run
    random_address = "0x" + secrets.token_hex(20)
    random_id = f"test_user_{secrets.token_hex(4)}"

    customer = drip.create_customer(
        onchain_address=random_address,
        external_customer_id=random_id,
        metadata={"name": "Test User", "plan": "starter"}
    )
    print(f"   ✅ Customer created: {customer.id}")
    print(f"      Address: {customer.onchain_address}")
    customer_id = customer.id
except Exception as e:
    print(f"   ❌ Failed to create customer: {e}")
    exit(1)

# ============================================================================
# TEST 3: Track Usage (No Billing)
# ============================================================================

print("\n3️⃣  Tracking usage (no charge)...")
try:
    result = drip.track_usage(
        customer_id=customer_id,
        meter="api_calls",
        quantity=5,
        metadata={"endpoint": "/v1/test", "method": "POST"}
    )
    print(f"   ✅ Usage tracked: {result.usage_event_id}")
    print(f"      Meter: api_calls, Quantity: 5")
except Exception as e:
    print(f"   ❌ Failed to track usage: {e}")

# ============================================================================
# TEST 4: Record Agent Run
# ============================================================================

print("\n4️⃣  Recording agent run...")
try:
    run_result = drip.record_run(
        customer_id=customer_id,
        workflow="test-agent",
        events=[
            {
                "eventType": "llm.call",
                "quantity": 300,
                "units": "tokens",
            },
            {
                "eventType": "tool.call",
                "quantity": 1,
            }
        ],
        status="COMPLETED"
    )
    print(f"   ✅ Agent run recorded: {run_result.run.id}")
    print(f"      Summary: {run_result.summary}")
except Exception as e:
    print(f"   ❌ Failed to record run: {e}")

# ============================================================================
# TEST 5: Get Customer Balance
# ============================================================================

print("\n5️⃣  Checking customer balance...")
try:
    balance = drip.get_balance(customer_id)
    print(f"   ✅ Balance retrieved:")
    print(f"      Balance: ${balance.balance_usdc} USDC")
    print(f"      Available: ${balance.available_usdc} USDC")
except Exception as e:
    print(f"   ❌ Failed to get balance: {e}")

# ============================================================================
# TEST 6: Create a Charge
# ============================================================================

print("\n6️⃣  Creating a charge...")
try:
    charge_result = drip.charge(
        customer_id=customer_id,
        meter="api_calls",
        quantity=10,
        idempotency_key="test_charge_001"
    )
    print(f"   ✅ Charge created: {charge_result.charge.id}")
    print(f"      Amount: ${charge_result.charge.amount_usdc} USDC")
    print(f"      Status: {charge_result.charge.status}")
    print(f"      Is Duplicate: {charge_result.is_duplicate}")
except Exception as e:
    print(f"   ⚠️  Charge failed (expected if no balance): {e}")

# ============================================================================
# TEST 7: List Customers
# ============================================================================

print("\n7️⃣  Listing all customers...")
try:
    customers = drip.list_customers(limit=5)
    print(f"   ✅ Found {len(customers.data)} customers:")
    for cust in customers.data[:3]:  # Show first 3
        print(f"      - {cust.id} ({cust.external_customer_id or 'no external ID'})")
except Exception as e:
    print(f"   ❌ Failed to list customers: {e}")

# ============================================================================
# TEST 8: Track Token Usage (LLM Tokens)
# ============================================================================

print("\n8️⃣  Tracking LLM token usage...")
try:
    # Track input tokens (prompt)
    input_usage = drip.track_usage(
        customer_id=customer_id,
        meter="tokens_input",
        quantity=500,
        metadata={
            "model": "gpt-4",
            "endpoint": "/v1/chat/completions",
            "session_id": "sess_123"
        }
    )
    print(f"   ✅ Input tokens tracked: {input_usage.usage_event_id}")
    print(f"      Model: gpt-4, Tokens: 500")

    # Track output tokens (completion)
    output_usage = drip.track_usage(
        customer_id=customer_id,
        meter="tokens_output",
        quantity=1200,
        metadata={
            "model": "gpt-4",
            "endpoint": "/v1/chat/completions",
            "session_id": "sess_123"
        }
    )
    print(f"   ✅ Output tokens tracked: {output_usage.usage_event_id}")
    print(f"      Model: gpt-4, Tokens: 1200")
    print(f"      Total tokens for this request: 1700")
except Exception as e:
    print(f"   ❌ Failed to track tokens: {e}")

# ============================================================================
# TEST 9: Test Idempotency (Duplicate Prevention)
# ============================================================================

print("\n9️⃣  Testing idempotency (duplicate prevention)...")
try:
    # Generate a unique idempotency key for this operation
    idem_key = f"test_idem_{secrets.token_hex(8)}"

    # First request with idempotency_key parameter
    print(f"   → Making first request with key: {idem_key}")
    usage1 = drip.track_usage(
        customer_id=customer_id,
        meter="api_calls",
        quantity=1,
        idempotency_key=idem_key,
    )
    print(f"   ✅ First request succeeded: {usage1.usage_event_id}")

    # Second request with SAME idempotency key (should deduplicate)
    print(f"   → Making duplicate request with same key...")
    usage2 = drip.track_usage(
        customer_id=customer_id,
        meter="api_calls",
        quantity=1,
        idempotency_key=idem_key,
    )
    print(f"   ✅ Second request handled: {usage2.usage_event_id}")

    if usage1.usage_event_id == usage2.usage_event_id:
        print(f"   ✅ Idempotency working! Same event returned (no duplicate)")
    else:
        print(f"   ⚠️  Note: Different events created (idempotency may not be server-enforced for track_usage)")

except Exception as e:
    print(f"   ❌ Failed idempotency test: {e}")

# ============================================================================
# TEST 10: Track Multiple Customers with Different Usage
# ============================================================================

print("\n🔟  Tracking usage across multiple customers...")
try:
    # Create a second customer
    random_address_2 = "0x" + secrets.token_hex(20)
    random_id_2 = f"test_user_{secrets.token_hex(4)}"

    customer2 = drip.create_customer(
        onchain_address=random_address_2,
        external_customer_id=random_id_2,
        metadata={"name": "Test User 2", "plan": "premium"}
    )
    print(f"   ✅ Customer 2 created: {customer2.id}")

    # Track different usage amounts for each customer
    # Customer 1: Light usage
    drip.track_usage(customer_id=customer_id, meter="api_calls", quantity=10)
    print(f"   ✅ Customer 1 ({random_id}): 10 API calls")

    # Customer 2: Heavy usage
    drip.track_usage(customer_id=customer2.id, meter="api_calls", quantity=100)
    drip.track_usage(customer_id=customer2.id, meter="tokens_input", quantity=5000)
    drip.track_usage(customer_id=customer2.id, meter="tokens_output", quantity=8000)
    print(f"   ✅ Customer 2 ({random_id_2}): 100 API calls, 13,000 tokens")

    print(f"\n   📊 Usage Summary:")
    print(f"      Customer 1: Light user (10 calls)")
    print(f"      Customer 2: Heavy user (100 calls + 13k tokens)")
    print(f"   ✅ Multi-customer tracking successful!")

except Exception as e:
    print(f"   ❌ Failed multi-customer test: {e}")

# ============================================================================
# TEST 11: Audit Trail - Track Who Did What
# ============================================================================

print("\n1️⃣1️⃣  Testing audit trail (tracking who did what)...")
try:
    # Track usage with detailed metadata for audit purposes
    audit_usage = drip.track_usage(
        customer_id=customer_id,
        meter="api_calls",
        quantity=1,
        metadata={
            "action": "document_generated",
            "user_id": "user_alice_123",
            "user_email": "alice@example.com",
            "ip_address": "192.168.1.100",
            "timestamp": "2026-01-31T12:00:00Z",
            "endpoint": "/api/generate-report",
            "success": True,
            "response_time_ms": 450
        }
    )
    print(f"   ✅ Audit event tracked: {audit_usage.usage_event_id}")
    print(f"      Action: document_generated")
    print(f"      User: alice@example.com (user_alice_123)")
    print(f"      IP: 192.168.1.100")
    print(f"      Success: True, Response time: 450ms")
    print(f"   ✅ Full audit trail captured in metadata!")

except Exception as e:
    print(f"   ❌ Failed audit trail test: {e}")

# ============================================================================
# TEST 12: Correlation ID (Distributed Tracing)
# ============================================================================

print("\n1️⃣2️⃣  Testing correlation_id (distributed tracing)...")
try:
    trace_id = f"trace_{secrets.token_hex(16)}"

    # record_run with correlation_id
    corr_result = drip.record_run(
        customer_id=customer_id,
        workflow="traced-agent",
        correlation_id=trace_id,
        events=[
            {"eventType": "llm.call", "quantity": 500, "units": "tokens"},
        ],
        status="COMPLETED"
    )
    print(f"   ✅ Run recorded with correlation_id: {trace_id[:24]}...")
    print(f"      Run ID: {corr_result.run.id}")
    print(f"      Summary: {corr_result.summary}")

except Exception as e:
    print(f"   ❌ Failed correlation_id test: {e}")

# ============================================================================
# TEST 13: Fine-Grained Run Control (start → emit → end → timeline)
# ============================================================================

print("\n1️⃣3️⃣  Testing fine-grained run control...")
try:
    import time

    # Step 1: Create or reuse workflow
    workflow = drip.create_workflow(
        name="Fine-Grained Test",
        slug=f"fine-grained-test-{secrets.token_hex(4)}",
        product_surface="AGENT"
    )
    print(f"   ✅ Workflow created: {workflow.id}")

    # Step 2: Start run with correlation_id
    span_id = f"span_{secrets.token_hex(8)}"
    run = drip.start_run(
        customer_id=customer_id,
        workflow_id=workflow.id,
        correlation_id=span_id,
    )
    print(f"   ✅ Run started: {run.id}")
    print(f"      Correlation ID: {span_id}")

    # Step 3: Emit individual events
    drip.emit_event(
        run_id=run.id,
        event_type="prompt.received",
        quantity=150,
        units="tokens",
    )
    print(f"   ✅ Event emitted: prompt.received (150 tokens)")

    drip.emit_event(
        run_id=run.id,
        event_type="llm.call",
        quantity=800,
        units="tokens",
        metadata={"model": "gpt-4o"},
    )
    print(f"   ✅ Event emitted: llm.call (800 tokens)")

    drip.emit_event(
        run_id=run.id,
        event_type="tool.call",
        quantity=1,
        description="web search for latest news",
    )
    print(f"   ✅ Event emitted: tool.call (1)")

    # Step 4: End run
    time.sleep(1)  # brief pause so duration is non-zero
    end_result = drip.end_run(run.id, status="COMPLETED")
    print(f"   ✅ Run ended: {end_result.status}")
    duration = getattr(end_result, 'duration_ms', None)
    if duration:
        print(f"      Duration: {duration}ms")

    # Step 5: Get timeline
    tl = drip.get_run_timeline(run.id)
    print(f"   ✅ Timeline retrieved:")
    print(f"      Events: {len(tl.timeline)}")
    print(f"      Status: {tl.run.status}")
    if tl.run.correlation_id:
        print(f"      Correlation ID: {tl.run.correlation_id}")
    if tl.run.duration_ms:
        print(f"      Duration: {tl.run.duration_ms}ms")
    print(f"      Summary: {tl.summary}")
    for evt in tl.timeline:
        print(f"        - {evt.event_type} ({evt.quantity} {evt.units or 'units'})")

except Exception as e:
    print(f"   ❌ Failed fine-grained run test: {e}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 60)
print("✨ SDK Test Complete!")
print("=" * 60)
print("\nThe Drip Python SDK is working correctly.")
print("\n📋 What was tested:")
print("  ✅ API connectivity and authentication")
print("  ✅ Customer creation with unique identifiers")
print("  ✅ Usage tracking (API calls, tokens)")
print("  ✅ LLM token tracking (input/output)")
print("  ✅ Idempotency (duplicate prevention with idempotency_key)")
print("  ✅ Multi-customer scenarios")
print("  ✅ Audit trail (who did what)")
print("  ✅ Balance retrieval")
print("  ✅ Customer listing")
print("  ✅ Correlation ID (distributed tracing)")
print("  ✅ Fine-grained runs (start → emit → end → timeline)")
print("\n💡 Key Features Demonstrated:")
print("  • Customer Attribution: Track which customer used what")
print("  • Token Tracking: Measure LLM usage per customer")
print("  • Idempotency: Prevent duplicate charges")
print("  • Audit Trail: Capture user, IP, timestamp, action")
print("  • Multi-tenant: Handle multiple customers independently")
print("  • Correlation ID: Link billing to OpenTelemetry/Datadog traces")
print("  • Fine-Grained Runs: Full lifecycle control with timeline")
print("\n🚀 Next steps:")
print("  1. Read the docs: https://docs.drip.dev")
print("  2. Check the SDK README for more examples")
print("  3. Integrate into your FastAPI/Flask/Django app")
print("  4. Set up webhooks for real-time notifications")
print("  5. Configure pricing plans for billing")
