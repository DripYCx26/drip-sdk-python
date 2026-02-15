"""Tests for the Drip client."""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
import respx

from drip import (
    AsyncDrip,
    ChargeStatus,
    Drip,
    DripAPIError,
    DripAuthenticationError,
    DripNetworkError,
    DripPaymentRequiredError,
    DripRateLimitError,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def api_key() -> str:
    return "drip_sk_test_123"


@pytest.fixture
def base_url() -> str:
    return "https://drip-app-hlunj.ondigitalocean.app/v1"


@pytest.fixture
def client(api_key: str, base_url: str) -> Drip:
    return Drip(api_key=api_key, base_url=base_url)


@pytest.fixture
def async_client(api_key: str, base_url: str) -> AsyncDrip:
    return AsyncDrip(api_key=api_key, base_url=base_url)


# =============================================================================
# Client Initialization Tests
# =============================================================================


class TestClientInitialization:
    def test_client_requires_api_key(self) -> None:
        """Client should raise error if no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove DRIP_API_KEY if present
            os.environ.pop("DRIP_API_KEY", None)
            with pytest.raises(DripAuthenticationError):
                Drip()

    def test_client_accepts_api_key_param(self, api_key: str) -> None:
        """Client should accept API key as parameter."""
        client = Drip(api_key=api_key)
        assert client.config.api_key == api_key

    def test_client_reads_api_key_from_env(self) -> None:
        """Client should read API key from environment."""
        with patch.dict(os.environ, {"DRIP_API_KEY": "env_key_123"}):
            client = Drip()
            assert client.config.api_key == "env_key_123"

    def test_client_default_base_url(self, api_key: str) -> None:
        """Client should use default base URL."""
        client = Drip(api_key=api_key)
        assert client.config.base_url == "https://drip-app-hlunj.ondigitalocean.app/v1"

    def test_client_custom_base_url(self, api_key: str) -> None:
        """Client should accept custom base URL."""
        client = Drip(api_key=api_key, base_url="https://custom.api.com")
        assert client.config.base_url == "https://custom.api.com"

    def test_client_context_manager(self, api_key: str) -> None:
        """Client should work as context manager."""
        with Drip(api_key=api_key) as client:
            assert client.config.api_key == api_key


class TestAsyncClientInitialization:
    def test_async_client_requires_api_key(self) -> None:
        """Async client should raise error if no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DRIP_API_KEY", None)
            with pytest.raises(DripAuthenticationError):
                AsyncDrip()

    @pytest.mark.asyncio
    async def test_async_client_context_manager(self, api_key: str) -> None:
        """Async client should work as async context manager."""
        async with AsyncDrip(api_key=api_key) as client:
            assert client.config.api_key == api_key


# =============================================================================
# Customer API Tests
# =============================================================================


class TestCustomerAPI:
    @respx.mock
    def test_create_customer(self, client: Drip, base_url: str) -> None:
        """Should create a customer."""
        respx.post(f"{base_url}/customers").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "cus_123",
                    "businessId": "biz_456",
                    "externalCustomerId": "ext_789",
                    "onchainAddress": "0x1234567890abcdef",
                    "metadata": {"key": "value"},
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                },
            )
        )

        customer = client.create_customer(
            onchain_address="0x1234567890abcdef",
            external_customer_id="ext_789",
            metadata={"key": "value"},
        )

        assert customer.id == "cus_123"
        assert customer.onchain_address == "0x1234567890abcdef"
        assert customer.external_customer_id == "ext_789"

    @respx.mock
    def test_get_customer(self, client: Drip, base_url: str) -> None:
        """Should get a customer by ID."""
        respx.get(f"{base_url}/customers/cus_123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "cus_123",
                    "businessId": "biz_456",
                    "externalCustomerId": None,
                    "onchainAddress": "0x1234",
                    "metadata": None,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                },
            )
        )

        customer = client.get_customer("cus_123")
        assert customer.id == "cus_123"

    @respx.mock
    def test_list_customers(self, client: Drip, base_url: str) -> None:
        """Should list customers."""
        respx.get(f"{base_url}/customers").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "cus_1",
                            "businessId": "biz_1",
                            "externalCustomerId": None,
                            "onchainAddress": "0x1",
                            "metadata": None,
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-01T00:00:00Z",
                        },
                        {
                            "id": "cus_2",
                            "businessId": "biz_1",
                            "externalCustomerId": None,
                            "onchainAddress": "0x2",
                            "metadata": None,
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-01T00:00:00Z",
                        },
                    ],
                    "count": 2,
                },
            )
        )

        result = client.list_customers()
        assert result.count == 2
        assert len(result.data) == 2

    @respx.mock
    def test_get_balance(self, client: Drip, base_url: str) -> None:
        """Should get customer balance."""
        respx.get(f"{base_url}/customers/cus_123/balance").mock(
            return_value=httpx.Response(
                200,
                json={
                    "customerId": "cus_123",
                    "onchainAddress": "0x1234567890abcdef1234567890abcdef12345678",
                    "balanceUsdc": "1000000",
                    "pendingChargesUsdc": "0",
                    "availableUsdc": "1000000",
                    "lastSyncedAt": "2024-01-01T00:00:00Z",
                },
            )
        )

        balance = client.get_balance("cus_123")
        assert balance.customer_id == "cus_123"
        assert balance.balance_usdc == "1000000"
        assert balance.available_usdc == "1000000"


# =============================================================================
# Charge API Tests
# =============================================================================


class TestChargeAPI:
    @respx.mock
    def test_charge(self, client: Drip, base_url: str) -> None:
        """Should create a charge."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "usageEventId": "usage_123",
                    "isDuplicate": False,
                    "charge": {
                        "id": "chg_123",
                        "amountUsdc": "100",
                        "amountToken": "100000000000000",
                        "txHash": "0xabc",
                        "status": "CONFIRMED",
                    },
                },
            )
        )

        result = client.charge(
            customer_id="cus_123",
            meter="api_calls",
            quantity=1,
        )

        assert result.success is True
        assert result.charge.id == "chg_123"
        assert result.charge.status == ChargeStatus.CONFIRMED

    @respx.mock
    def test_charge_with_idempotency(self, client: Drip, base_url: str) -> None:
        """Should create a charge with idempotency key."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "usageEventId": "usage_123",
                    "isDuplicate": True,
                    "charge": {
                        "id": "chg_123",
                        "amountUsdc": "100",
                        "amountToken": "100000000000000",
                        "txHash": "0xabc",
                        "status": "CONFIRMED",
                    },
                },
            )
        )

        result = client.charge(
            customer_id="cus_123",
            meter="api_calls",
            quantity=1,
            idempotency_key="idem_123",
        )

        assert result.is_duplicate is True

    @respx.mock
    def test_get_charge(self, client: Drip, base_url: str) -> None:
        """Should get charge details."""
        respx.get(f"{base_url}/charges/chg_123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "chg_123",
                    "usageId": "usage_123",
                    "customerId": "cus_123",
                    "customer": {
                        "id": "cus_123",
                        "onchainAddress": "0x123",
                        "externalCustomerId": None,
                    },
                    "usageEvent": {
                        "id": "usage_123",
                        "type": "api_calls",
                        "quantity": "1",
                        "metadata": None,
                    },
                    "amountUsdc": "100",
                    "amountToken": "100000000000000",
                    "txHash": "0xabc",
                    "blockNumber": "12345",
                    "status": "CONFIRMED",
                    "failureReason": None,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "confirmedAt": "2024-01-01T00:00:01Z",
                },
            )
        )

        charge = client.get_charge("chg_123")
        assert charge.id == "chg_123"
        assert charge.customer.id == "cus_123"


# =============================================================================
# Webhook API Tests
# =============================================================================


class TestWebhookAPI:
    @respx.mock
    def test_create_webhook(self, client: Drip, base_url: str) -> None:
        """Should create a webhook."""
        respx.post(f"{base_url}/webhooks").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "wh_123",
                    "url": "https://example.com/webhook",
                    "events": ["charge.succeeded"],
                    "description": "Test webhook",
                    "isActive": True,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                    "secret": "whsec_abc123",
                    "message": "Webhook created",
                },
            )
        )

        result = client.create_webhook(
            url="https://example.com/webhook",
            events=["charge.succeeded"],
            description="Test webhook",
        )

        assert result.id == "wh_123"
        assert result.secret == "whsec_abc123"

    @respx.mock
    def test_list_webhooks(self, client: Drip, base_url: str) -> None:
        """Should list webhooks."""
        respx.get(f"{base_url}/webhooks").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wh_1",
                            "url": "https://example.com/wh1",
                            "events": ["charge.succeeded"],
                            "description": None,
                            "isActive": True,
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-01T00:00:00Z",
                        }
                    ],
                    "count": 1,
                },
            )
        )

        result = client.list_webhooks()
        assert result.count == 1


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    @respx.mock
    def test_authentication_error(self, client: Drip, base_url: str) -> None:
        """Should raise DripAuthenticationError on 401."""
        respx.get(f"{base_url}/customers/cus_123").mock(
            return_value=httpx.Response(
                401,
                json={"message": "Invalid API key"},
            )
        )

        with pytest.raises(DripAuthenticationError):
            client.get_customer("cus_123")

    @respx.mock
    def test_payment_required_error(self, client: Drip, base_url: str) -> None:
        """Should raise DripPaymentRequiredError on 402."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                402,
                json={
                    "message": "Insufficient balance",
                    "paymentRequest": {
                        "amount": "1000",
                        "recipient": "0x123",
                    },
                },
            )
        )

        with pytest.raises(DripPaymentRequiredError) as exc_info:
            client.charge(customer_id="cus_123", meter="api_calls", quantity=1)

        assert exc_info.value.payment_request is not None

    @respx.mock
    def test_rate_limit_error(self, client: Drip, base_url: str) -> None:
        """Should raise DripRateLimitError on 429."""
        respx.get(f"{base_url}/customers").mock(
            return_value=httpx.Response(
                429,
                json={"message": "Too many requests", "retryAfter": 60},
            )
        )

        with pytest.raises(DripRateLimitError) as exc_info:
            client.list_customers()

        assert exc_info.value.retry_after == 60

    @respx.mock
    def test_api_error(self, client: Drip, base_url: str) -> None:
        """Should raise DripAPIError on 4xx/5xx."""
        respx.get(f"{base_url}/customers/invalid").mock(
            return_value=httpx.Response(
                404,
                json={"message": "Customer not found", "code": "NOT_FOUND"},
            )
        )

        with pytest.raises(DripAPIError) as exc_info:
            client.get_customer("invalid")

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "NOT_FOUND"

    @respx.mock
    def test_network_error(self, client: Drip, base_url: str) -> None:
        """Should raise DripNetworkError on connection issues."""
        respx.get(f"{base_url}/customers").mock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(DripNetworkError):
            client.list_customers()


# =============================================================================
# Async Client Tests
# =============================================================================


class TestAsyncClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_create_customer(
        self, async_client: AsyncDrip, base_url: str
    ) -> None:
        """Should create customer asynchronously."""
        respx.post(f"{base_url}/customers").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "cus_123",
                    "businessId": "biz_456",
                    "externalCustomerId": None,
                    "onchainAddress": "0x123",
                    "metadata": None,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                },
            )
        )

        customer = await async_client.create_customer(onchain_address="0x123")
        assert customer.id == "cus_123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_charge(self, async_client: AsyncDrip, base_url: str) -> None:
        """Should create charge asynchronously."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "usageEventId": "usage_123",
                    "isDuplicate": False,
                    "charge": {
                        "id": "chg_123",
                        "amountUsdc": "100",
                        "amountToken": "100000000000000",
                        "txHash": "0xabc",
                        "status": "CONFIRMED",
                    },
                },
            )
        )

        result = await async_client.charge(
            customer_id="cus_123",
            meter="api_calls",
            quantity=1,
        )

        assert result.success is True


# =============================================================================
# Utility Method Tests
# =============================================================================


class TestUtilityMethods:
    def test_generate_idempotency_key(self) -> None:
        """Should generate deterministic idempotency keys."""
        key1 = Drip.generate_idempotency_key(
            customer_id="cus_123",
            step_name="process",
            run_id="run_456",
        )
        key2 = Drip.generate_idempotency_key(
            customer_id="cus_123",
            step_name="process",
            run_id="run_456",
        )
        key3 = Drip.generate_idempotency_key(
            customer_id="cus_123",
            step_name="different",
            run_id="run_456",
        )

        # Same inputs should produce same key
        assert key1 == key2
        # Different inputs should produce different key
        assert key1 != key3

    def test_verify_webhook_signature_valid(self) -> None:
        """Should verify valid webhook signatures using t=timestamp,v1=signature format."""
        from drip.utils import generate_webhook_signature

        secret = "whsec_test123"
        payload = '{"event": "charge.succeeded"}'
        # Use generate_webhook_signature to create proper format
        signature = generate_webhook_signature(payload, secret)

        assert Drip.verify_webhook_signature(payload, signature, secret) is True

    def test_verify_webhook_signature_invalid(self) -> None:
        """Should reject invalid webhook signatures."""
        secret = "whsec_test123"
        payload = '{"event": "charge.succeeded"}'
        signature = "t=123,v1=invalid"

        assert Drip.verify_webhook_signature(payload, signature, secret) is False

    def test_verify_webhook_signature_empty(self) -> None:
        """Should handle empty values."""
        assert Drip.verify_webhook_signature("", "sig", "secret") is False
        assert Drip.verify_webhook_signature("payload", "", "secret") is False
        assert Drip.verify_webhook_signature("payload", "sig", "") is False


# =============================================================================
# Resilience Integration Tests
# =============================================================================


class TestClientResilience:
    """Tests for resilience integration in clients."""

    def test_drip_with_resilience_enabled(self, api_key: str, base_url: str) -> None:
        """Client should work with resilience=True."""
        client = Drip(api_key=api_key, base_url=base_url, resilience=True)
        assert client.resilience is not None
        assert client.get_health() is not None
        assert client.get_metrics() is not None

    def test_drip_without_resilience(self, api_key: str, base_url: str) -> None:
        """Client should work without resilience (default)."""
        client = Drip(api_key=api_key, base_url=base_url)
        assert client.resilience is None
        assert client.get_health() is None
        assert client.get_metrics() is None

    def test_async_drip_with_resilience_enabled(
        self, api_key: str, base_url: str
    ) -> None:
        """Async client should work with resilience=True."""
        client = AsyncDrip(api_key=api_key, base_url=base_url, resilience=True)
        assert client.resilience is not None
        assert client.get_health() is not None
        assert client.get_metrics() is not None

    def test_async_drip_without_resilience(self, api_key: str, base_url: str) -> None:
        """Async client should work without resilience (default)."""
        client = AsyncDrip(api_key=api_key, base_url=base_url)
        assert client.resilience is None
        assert client.get_health() is None
        assert client.get_metrics() is None

    @respx.mock
    def test_resilience_collects_metrics(
        self, api_key: str, base_url: str
    ) -> None:
        """Resilient client should collect metrics on requests."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "usageEventId": "u123",
                    "isDuplicate": False,
                    "charge": {
                        "id": "chg_123",
                        "amountUsdc": "100",
                        "amountToken": "100000000000000",
                        "txHash": "0xabc",
                        "status": "CONFIRMED",
                    },
                },
            )
        )

        client = Drip(api_key=api_key, base_url=base_url, resilience=True)
        client.charge(customer_id="cus_123", meter="api_calls", quantity=1)

        metrics = client.get_metrics()
        assert metrics is not None
        assert metrics["total_requests"] == 1
        assert metrics["total_successes"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_resilience_collects_metrics(
        self, api_key: str, base_url: str
    ) -> None:
        """Async resilient client should collect metrics on requests."""
        respx.post(f"{base_url}/usage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "usageEventId": "u123",
                    "isDuplicate": False,
                    "charge": {
                        "id": "chg_123",
                        "amountUsdc": "100",
                        "amountToken": "100000000000000",
                        "txHash": "0xabc",
                        "status": "CONFIRMED",
                    },
                },
            )
        )

        async with AsyncDrip(
            api_key=api_key, base_url=base_url, resilience=True
        ) as client:
            await client.charge(customer_id="cus_123", meter="api_calls", quantity=1)

            metrics = client.get_metrics()
            assert metrics is not None
            assert metrics["total_requests"] == 1
            assert metrics["total_successes"] == 1
