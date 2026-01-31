"""Comprehensive tests for AsyncDrip client.

This module tests all async methods including:
- Customer operations
- Charge operations
- Usage tracking
- Workflow and run management
- Webhook operations
- Cost estimation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import respx
from httpx import Response

if TYPE_CHECKING:
    from drip import AsyncDrip


# =============================================================================
# Customer Operations
# =============================================================================


class TestAsyncCustomerOperations:
    """Test async customer management operations."""

    @pytest.mark.asyncio
    async def test_async_create_customer(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_customer_response: dict[str, Any],
    ) -> None:
        """Test async customer creation."""
        mock_api.post("/customers").mock(
            return_value=Response(200, json=mock_customer_response)
        )

        customer = await mock_async_client.create_customer(
            onchain_address="0x1234567890abcdef1234567890abcdef12345678",
            external_customer_id="ext_123",
            email="test@example.com",
        )

        assert customer.id == "cus_test_123"
        assert customer.external_customer_id == "ext_123"

    @pytest.mark.asyncio
    async def test_async_get_customer(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_customer_response: dict[str, Any],
    ) -> None:
        """Test async customer retrieval."""
        mock_api.get("/customers/cus_test_123").mock(
            return_value=Response(200, json=mock_customer_response)
        )

        customer = await mock_async_client.get_customer("cus_test_123")

        assert customer.id == "cus_test_123"
        assert customer.status == "active"

    @pytest.mark.asyncio
    async def test_async_list_customers(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_customer_response: dict[str, Any],
    ) -> None:
        """Test async customer listing."""
        mock_api.get("/customers").mock(
            return_value=Response(
                200,
                json={
                    "customers": [mock_customer_response],
                    "has_more": False,
                    "total": 1,
                },
            )
        )

        result = await mock_async_client.list_customers(limit=10)

        assert len(result.customers) == 1
        assert result.customers[0].id == "cus_test_123"


# =============================================================================
# Charge Operations
# =============================================================================


class TestAsyncChargeOperations:
    """Test async charge operations."""

    @pytest.mark.asyncio
    async def test_async_charge(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_charge_response: dict[str, Any],
    ) -> None:
        """Test async charge creation."""
        mock_api.post("/charges").mock(
            return_value=Response(200, json={"charge": mock_charge_response})
        )

        result = await mock_async_client.charge(
            customer_id="cus_test_123",
            meter="api_calls",
            quantity=1,
        )

        assert result.charge.id == "chg_test_123"
        assert result.charge.status == "settled"

    @pytest.mark.asyncio
    async def test_async_get_charge_status(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_charge_response: dict[str, Any],
    ) -> None:
        """Test async get_charge_status."""
        mock_api.get("/charges/chg_test_123").mock(
            return_value=Response(200, json=mock_charge_response)
        )

        status = await mock_async_client.get_charge_status("chg_test_123")

        assert status.status in ["pending", "settled", "failed"]

    @pytest.mark.asyncio
    async def test_async_charge_with_idempotency_key(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_charge_response: dict[str, Any],
    ) -> None:
        """Test async charge with idempotency key."""
        mock_api.post("/charges").mock(
            return_value=Response(200, json={"charge": mock_charge_response})
        )

        result = await mock_async_client.charge(
            customer_id="cus_test_123",
            meter="api_calls",
            quantity=1,
            idempotency_key="test_key_123",
        )

        assert result.charge.id == "chg_test_123"


# =============================================================================
# Usage Tracking
# =============================================================================


class TestAsyncUsageTracking:
    """Test async usage tracking operations."""

    @pytest.mark.asyncio
    async def test_async_track_usage(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async track_usage."""
        mock_api.post("/usage/track").mock(
            return_value=Response(200, json={"recorded": True})
        )

        result = await mock_async_client.track_usage(
            customer_id="cus_test_123",
            meter="api_calls",
            quantity=1,
            description="Async usage test",
        )

        assert result.recorded is True

    @pytest.mark.asyncio
    async def test_async_track_usage_with_metadata(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async track_usage with metadata."""
        mock_api.post("/usage/track").mock(
            return_value=Response(200, json={"recorded": True})
        )

        result = await mock_async_client.track_usage(
            customer_id="cus_test_123",
            meter="tokens",
            quantity=100,
            description="Token usage",
            metadata={"model": "gpt-4", "request_id": "req_123"},
        )

        assert result.recorded is True


# =============================================================================
# Wrap API Call
# =============================================================================


class TestAsyncWrapApiCall:
    """Test async wrap_api_call operations."""

    @pytest.mark.asyncio
    async def test_async_wrap_api_call(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_charge_response: dict[str, Any],
    ) -> None:
        """Test async wrap_api_call."""
        mock_api.post("/charges").mock(
            return_value=Response(200, json={"charge": mock_charge_response})
        )

        async def mock_api_call() -> dict[str, Any]:
            return {"tokens": 50}

        result = await mock_async_client.wrap_api_call(
            call=mock_api_call,
            customer_id="cus_test_123",
            meter="tokens",
            extract_usage=lambda r: r["tokens"],
        )

        assert result.result == {"tokens": 50}
        assert result.charge is not None

    @pytest.mark.asyncio
    async def test_async_wrap_api_call_with_error(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async wrap_api_call handles errors gracefully."""

        async def failing_api_call() -> dict[str, Any]:
            raise ValueError("API call failed")

        with pytest.raises(ValueError, match="API call failed"):
            await mock_async_client.wrap_api_call(
                call=failing_api_call,
                customer_id="cus_test_123",
                meter="tokens",
                extract_usage=lambda r: r.get("tokens", 0),
            )


# =============================================================================
# Cost Estimation
# =============================================================================


class TestAsyncCostEstimation:
    """Test async cost estimation operations."""

    @pytest.mark.asyncio
    async def test_async_estimate_from_usage(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async cost estimation from usage."""
        mock_api.post("/estimates/usage").mock(
            return_value=Response(
                200,
                json={
                    "total_cost": "1000000",
                    "line_items": [
                        {"meter": "api_calls", "quantity": 100, "cost": "1000000"}
                    ],
                },
            )
        )

        result = await mock_async_client.estimate_from_usage(
            customer_id="cus_test_123",
            period_start="2024-01-01",
            period_end="2024-01-31",
        )

        assert result.total_cost is not None

    @pytest.mark.asyncio
    async def test_async_estimate_from_hypothetical(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async hypothetical cost estimation."""
        mock_api.post("/estimates/hypothetical").mock(
            return_value=Response(
                200,
                json={
                    "total_cost": "500000",
                    "line_items": [
                        {"meter": "tokens", "quantity": 10000, "cost": "500000"}
                    ],
                },
            )
        )

        result = await mock_async_client.estimate_from_hypothetical(
            items=[{"meter": "tokens", "quantity": 10000}]
        )

        assert result is not None


# =============================================================================
# Workflow Operations
# =============================================================================


class TestAsyncWorkflowOperations:
    """Test async workflow operations."""

    @pytest.mark.asyncio
    async def test_async_create_workflow(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_workflow_response: dict[str, Any],
        unique_id: str,
    ) -> None:
        """Test async create_workflow."""
        response = {
            **mock_workflow_response,
            "name": f"Async Test Workflow {unique_id}",
            "slug": f"async-test-{unique_id}",
        }
        mock_api.post("/workflows").mock(return_value=Response(200, json=response))

        workflow = await mock_async_client.create_workflow(
            name=f"Async Test Workflow {unique_id}",
            slug=f"async-test-{unique_id}",
            description="Created via async client",
        )

        assert workflow.id is not None
        assert unique_id in workflow.slug

    @pytest.mark.asyncio
    async def test_async_list_workflows(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_workflow_response: dict[str, Any],
    ) -> None:
        """Test async workflow listing."""
        mock_api.get("/workflows").mock(
            return_value=Response(
                200,
                json={
                    "workflows": [mock_workflow_response],
                    "has_more": False,
                    "total": 1,
                },
            )
        )

        result = await mock_async_client.list_workflows()

        assert len(result.workflows) >= 1


# =============================================================================
# Run Operations
# =============================================================================


class TestAsyncRunOperations:
    """Test async run operations."""

    @pytest.mark.asyncio
    async def test_async_start_run(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_run_response: dict[str, Any],
    ) -> None:
        """Test async start_run."""
        mock_api.post("/runs").mock(return_value=Response(200, json=mock_run_response))

        run = await mock_async_client.start_run(
            workflow_id="wf_test_123",
            customer_id="cus_test_123",
        )

        assert run.id is not None

    @pytest.mark.asyncio
    async def test_async_emit_event(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async emit_event."""
        mock_api.post("/runs/run_test_123/events").mock(
            return_value=Response(200, json={"id": "evt_test_123"})
        )

        result = await mock_async_client.emit_event(
            run_id="run_test_123",
            event_type="llm_call",
            quantity=100,
            units="tokens",
            metadata={"model": "gpt-4"},
        )

        assert result.id is not None

    @pytest.mark.asyncio
    async def test_async_emit_events_batch(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async batch event emission."""
        mock_api.post("/runs/run_test_123/events/batch").mock(
            return_value=Response(200, json={"count": 2})
        )

        result = await mock_async_client.emit_events_batch(
            run_id="run_test_123",
            events=[
                {"type": "tool_call", "data": {"tool": "search"}},
                {"type": "tool_call", "data": {"tool": "calc"}},
            ],
        )

        assert result.count == 2

    @pytest.mark.asyncio
    async def test_async_get_run_timeline(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async get_run_timeline."""
        mock_api.get("/runs/run_test_123/timeline").mock(
            return_value=Response(
                200,
                json={
                    "events": [
                        {"type": "llm_call", "data": {"model": "gpt-4", "tokens": 100}}
                    ]
                },
            )
        )

        timeline = await mock_async_client.get_run_timeline("run_test_123")

        assert len(timeline.events) >= 1

    @pytest.mark.asyncio
    async def test_async_record_run(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_run_response: dict[str, Any],
    ) -> None:
        """Test async record_run (simplified run recording)."""
        mock_api.post("/runs/record").mock(
            return_value=Response(200, json={"run": mock_run_response})
        )

        result = await mock_async_client.record_run(
            workflow="test-workflow",
            customer_id="cus_test_123",
            status="COMPLETED",
            events=[{"type": "llm_call", "data": {"model": "gpt-4", "tokens": 100}}],
        )

        assert result.run.id is not None

    @pytest.mark.asyncio
    async def test_async_end_run(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async end_run."""
        mock_api.post("/runs/run_test_123/end").mock(
            return_value=Response(
                200, json={"id": "run_test_123", "status": "completed"}
            )
        )

        result = await mock_async_client.end_run(
            run_id="run_test_123",
            status="COMPLETED",
        )

        assert result is not None


# =============================================================================
# Webhook Operations
# =============================================================================


class TestAsyncWebhookOperations:
    """Test async webhook operations."""

    @pytest.mark.asyncio
    async def test_async_create_webhook(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_webhook_response: dict[str, Any],
        test_webhook_url: str,
    ) -> None:
        """Test async create_webhook."""
        mock_api.post("/webhooks").mock(
            return_value=Response(200, json=mock_webhook_response)
        )

        webhook = await mock_async_client.create_webhook(
            url=test_webhook_url,
            events=["charge.created"],
        )

        assert webhook.id is not None
        assert webhook.secret is not None

    @pytest.mark.asyncio
    async def test_async_get_webhook(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
        mock_webhook_response: dict[str, Any],
    ) -> None:
        """Test async get_webhook."""
        mock_api.get("/webhooks/wh_test_123").mock(
            return_value=Response(200, json=mock_webhook_response)
        )

        webhook = await mock_async_client.get_webhook("wh_test_123")

        assert webhook.url == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_async_delete_webhook(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async delete_webhook."""
        mock_api.delete("/webhooks/wh_test_123").mock(
            return_value=Response(200, json={"deleted": True})
        )

        result = await mock_async_client.delete_webhook("wh_test_123")

        assert result.deleted is True

    @pytest.mark.asyncio
    async def test_async_test_webhook(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async test_webhook."""
        mock_api.post("/webhooks/wh_test_123/test").mock(
            return_value=Response(200, json={"success": True, "sent": True})
        )

        result = await mock_async_client.test_webhook("wh_test_123")

        assert result.success is True or result.sent is True

    @pytest.mark.asyncio
    async def test_async_rotate_webhook_secret(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async rotate_webhook_secret."""
        mock_api.post("/webhooks/wh_test_123/rotate-secret").mock(
            return_value=Response(200, json={"secret": "whsec_new_secret_67890"})
        )

        result = await mock_async_client.rotate_webhook_secret("wh_test_123")

        assert result.secret == "whsec_new_secret_67890"


# =============================================================================
# Context Manager
# =============================================================================


class TestAsyncContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self,
        api_key: str,
        mock_api: respx.MockRouter,
    ) -> None:
        """Test AsyncDrip as context manager."""
        from drip import AsyncDrip

        mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))

        async with AsyncDrip(
            api_key=api_key, base_url="https://api.drip.dev/v1"
        ) as client:
            assert client is not None

    @pytest.mark.asyncio
    async def test_async_client_close(
        self,
        api_key: str,
    ) -> None:
        """Test explicit close on async client."""
        from drip import AsyncDrip

        client = AsyncDrip(api_key=api_key, base_url="https://api.drip.dev/v1")
        await client.close()


# =============================================================================
# Error Handling
# =============================================================================


class TestAsyncErrorHandling:
    """Test async error handling."""

    @pytest.mark.asyncio
    async def test_async_handles_network_error(
        self,
        api_key: str,
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async client handles network errors."""
        from drip import AsyncDrip, DripNetworkError
        import httpx

        mock_api.get("/health").mock(side_effect=httpx.ConnectError("Connection failed"))

        async with AsyncDrip(
            api_key=api_key, base_url="https://api.drip.dev/v1"
        ) as client:
            with pytest.raises((DripNetworkError, httpx.ConnectError)):
                await client.ping()

    @pytest.mark.asyncio
    async def test_async_handles_api_error(
        self,
        mock_async_client: "AsyncDrip",
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async client handles API errors."""
        from drip import DripAPIError

        mock_api.post("/customers").mock(
            return_value=Response(
                400,
                json={"error": {"message": "Invalid request", "code": "INVALID_REQUEST"}},
            )
        )

        with pytest.raises(DripAPIError):
            await mock_async_client.create_customer(
                onchain_address="invalid_address",
            )

    @pytest.mark.asyncio
    async def test_async_handles_auth_error(
        self,
        mock_api: respx.MockRouter,
    ) -> None:
        """Test async client handles auth errors."""
        from drip import AsyncDrip, DripAuthenticationError

        mock_api.get("/health").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )

        async with AsyncDrip(
            api_key="invalid_key", base_url="https://api.drip.dev/v1"
        ) as client:
            with pytest.raises(DripAuthenticationError):
                await client.ping()
