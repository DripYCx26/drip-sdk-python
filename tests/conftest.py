"""Shared pytest fixtures for Drip SDK tests."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any, Generator
from unittest.mock import MagicMock, AsyncMock

import pytest
import respx
from httpx import Response

if TYPE_CHECKING:
    from drip import AsyncDrip, Drip


# =============================================================================
# Environment Configuration
# =============================================================================


@pytest.fixture(scope="session")
def api_key() -> str:
    """Return test API key."""
    return os.environ.get("DRIP_API_KEY", "drip_sk_test_12345")


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return test API base URL."""
    return os.environ.get("DRIP_API_URL", "https://api.drip.dev/v1")


@pytest.fixture
def unique_id() -> str:
    """Generate a unique ID for test isolation."""
    return str(uuid.uuid4())[:8]


# =============================================================================
# Mock HTTP Responses
# =============================================================================


@pytest.fixture
def mock_api() -> Generator[respx.MockRouter, None, None]:
    """Provide a respx mock router for API calls."""
    with respx.mock(base_url="https://api.drip.dev/v1") as router:
        yield router


@pytest.fixture
def mock_customer_response() -> dict[str, Any]:
    """Return a mock customer response."""
    return {
        "id": "cus_test_123",
        "onchain_address": "0x1234567890abcdef1234567890abcdef12345678",
        "external_customer_id": "ext_123",
        "status": "active",
        "email": "test@example.com",
        "name": "Test Customer",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_charge_response() -> dict[str, Any]:
    """Return a mock charge response."""
    return {
        "id": "chg_test_123",
        "customer_id": "cus_test_123",
        "meter": "api_calls",
        "quantity": 1.0,
        "amount_usdc": "100000",
        "status": "settled",
        "idempotency_key": None,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_webhook_response() -> dict[str, Any]:
    """Return a mock webhook response."""
    return {
        "id": "wh_test_123",
        "url": "https://example.com/webhook",
        "events": ["charge.created", "charge.settled"],
        "secret": "whsec_test_secret_12345",
        "enabled": True,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_workflow_response() -> dict[str, Any]:
    """Return a mock workflow response."""
    return {
        "id": "wf_test_123",
        "name": "Test Workflow",
        "slug": "test-workflow",
        "description": "A test workflow",
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_run_response() -> dict[str, Any]:
    """Return a mock run response."""
    return {
        "id": "run_test_123",
        "workflow_id": "wf_test_123",
        "customer_id": "cus_test_123",
        "status": "running",
        "started_at": "2024-01-01T00:00:00Z",
    }


# =============================================================================
# Sync Client Fixtures
# =============================================================================


@pytest.fixture
def client(api_key: str, base_url: str) -> Generator["Drip", None, None]:
    """Create a Drip client for testing."""
    from drip import Drip

    client = Drip(api_key=api_key, base_url=base_url)
    yield client
    client.close()


@pytest.fixture
def mock_client(
    api_key: str,
    mock_api: respx.MockRouter,
    mock_customer_response: dict[str, Any],
    mock_charge_response: dict[str, Any],
) -> Generator["Drip", None, None]:
    """Create a Drip client with mocked API responses."""
    from drip import Drip

    # Set up common mock routes
    mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))
    mock_api.post("/customers").mock(
        return_value=Response(200, json=mock_customer_response)
    )
    mock_api.get("/customers/cus_test_123").mock(
        return_value=Response(200, json=mock_customer_response)
    )
    mock_api.post("/charges").mock(
        return_value=Response(200, json={"charge": mock_charge_response})
    )

    client = Drip(api_key=api_key, base_url="https://api.drip.dev/v1")
    yield client
    client.close()


# =============================================================================
# Async Client Fixtures
# =============================================================================


@pytest.fixture
async def async_client(api_key: str, base_url: str) -> "AsyncDrip":
    """Create an AsyncDrip client for testing."""
    from drip import AsyncDrip

    client = AsyncDrip(api_key=api_key, base_url=base_url)
    yield client
    await client.close()


@pytest.fixture
async def mock_async_client(
    api_key: str,
    mock_api: respx.MockRouter,
    mock_customer_response: dict[str, Any],
    mock_charge_response: dict[str, Any],
    mock_webhook_response: dict[str, Any],
    mock_workflow_response: dict[str, Any],
    mock_run_response: dict[str, Any],
) -> "AsyncDrip":
    """Create an AsyncDrip client with mocked API responses."""
    from drip import AsyncDrip

    # Set up common mock routes
    mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))

    # Customer routes
    mock_api.post("/customers").mock(
        return_value=Response(200, json=mock_customer_response)
    )
    mock_api.get("/customers/cus_test_123").mock(
        return_value=Response(200, json=mock_customer_response)
    )

    # Charge routes
    mock_api.post("/charges").mock(
        return_value=Response(200, json={"charge": mock_charge_response})
    )
    mock_api.get("/charges/chg_test_123").mock(
        return_value=Response(200, json=mock_charge_response)
    )

    # Webhook routes
    mock_api.post("/webhooks").mock(
        return_value=Response(200, json=mock_webhook_response)
    )
    mock_api.get("/webhooks/wh_test_123").mock(
        return_value=Response(200, json=mock_webhook_response)
    )
    mock_api.delete("/webhooks/wh_test_123").mock(
        return_value=Response(200, json={"deleted": True})
    )
    mock_api.post("/webhooks/wh_test_123/test").mock(
        return_value=Response(200, json={"success": True, "sent": True})
    )
    mock_api.post("/webhooks/wh_test_123/rotate-secret").mock(
        return_value=Response(200, json={"secret": "whsec_new_secret_67890"})
    )

    # Workflow routes
    mock_api.post("/workflows").mock(
        return_value=Response(200, json=mock_workflow_response)
    )
    mock_api.get("/workflows/wf_test_123").mock(
        return_value=Response(200, json=mock_workflow_response)
    )

    # Run routes
    mock_api.post("/runs").mock(
        return_value=Response(200, json=mock_run_response)
    )
    mock_api.post("/runs/run_test_123/events").mock(
        return_value=Response(200, json={"id": "evt_test_123"})
    )
    mock_api.post("/runs/run_test_123/events/batch").mock(
        return_value=Response(200, json={"count": 2})
    )
    mock_api.get("/runs/run_test_123/timeline").mock(
        return_value=Response(200, json={"events": [{"type": "llm_call"}]})
    )
    mock_api.post("/runs/record").mock(
        return_value=Response(200, json={"run": mock_run_response})
    )

    # Usage routes
    mock_api.post("/usage/track").mock(
        return_value=Response(200, json={"recorded": True})
    )

    # Estimation routes
    mock_api.post("/estimates/usage").mock(
        return_value=Response(200, json={"total_cost": "1000000"})
    )
    mock_api.post("/estimates/hypothetical").mock(
        return_value=Response(200, json={"total_cost": "500000"})
    )

    client = AsyncDrip(api_key=api_key, base_url="https://api.drip.dev/v1")
    yield client
    await client.close()


# =============================================================================
# Resilience Fixtures
# =============================================================================


@pytest.fixture
def resilient_client(api_key: str, base_url: str) -> Generator["Drip", None, None]:
    """Create a Drip client with resilience enabled."""
    from drip import Drip
    from drip.resilience import ResilienceConfig

    client = Drip(
        api_key=api_key,
        base_url=base_url,
        resilience=ResilienceConfig.default(),
    )
    yield client
    client.close()


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def test_customer_id() -> str:
    """Return a test customer ID."""
    return "cus_test_123"


@pytest.fixture
def test_workflow_id() -> str:
    """Return a test workflow ID."""
    return "wf_test_123"


@pytest.fixture
def test_run_id() -> str:
    """Return a test run ID."""
    return "run_test_123"


@pytest.fixture
def test_webhook_url() -> str:
    """Return a test webhook URL."""
    return "https://example.com/webhook"


@pytest.fixture
def test_webhook_secret() -> str:
    """Return a test webhook secret."""
    return "whsec_test_secret_12345"


# =============================================================================
# LangChain Fixtures
# =============================================================================


@pytest.fixture
def mock_llm_response() -> MagicMock:
    """Create a mock LLM response."""
    response = MagicMock()
    response.llm_output = {
        "token_usage": {
            "prompt_tokens": 50,
            "completion_tokens": 100,
            "total_tokens": 150,
        }
    }
    return response


@pytest.fixture
def mock_serialized_llm() -> dict[str, Any]:
    """Create mock serialized LLM data."""
    return {
        "name": "gpt-4",
        "id": ["openai", "gpt-4"],
    }


@pytest.fixture
def mock_serialized_tool() -> dict[str, Any]:
    """Create mock serialized tool data."""
    return {
        "name": "calculator",
        "description": "A calculator tool",
    }


@pytest.fixture
def mock_serialized_chain() -> dict[str, Any]:
    """Create mock serialized chain data."""
    return {
        "name": "LLMChain",
        "id": ["langchain", "chains", "LLMChain"],
    }
