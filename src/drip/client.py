"""
Drip SDK client.

This module provides the main Drip client class for interacting with
the Drip API for usage-based billing with on-chain settlement.

Idempotency Keys
----------------
Every mutating method (``charge``, ``track_usage``, ``emit_event``)
accepts an optional ``idempotency_key``. The server uses this key to
deduplicate requests.

**Auto-generated keys (default):**
When you omit ``idempotency_key``, the SDK generates a deterministic key
that is unique per call (a monotonic counter distinguishes rapid identical
calls) but stable across retries of the same call.

Note: ``wrap_api_call`` generates a time-based key when no explicit
``idempotency_key`` is provided. Pass your own key if you need
deterministic deduplication with ``wrap_api_call``.

**When to pass explicit keys:**
Use your own ``idempotency_key`` for application-level deduplication —
e.g., ``f"order_{order_id}_charge"`` to guarantee one charge per order
even across process restarts.
"""

from __future__ import annotations

import asyncio
import json as _json_mod
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

import httpx

from .errors import (
    DripAuthenticationError,
    DripError,
    DripNetworkError,
    create_api_error_from_response,
)
from .models import (
    BalanceResult,
    Charge,
    ChargeResult,
    ChargeStatusResult,
    CheckoutResult,
    CostEstimateResponse,
    CreateWebhookResponse,
    Customer,
    CustomerStatus,
    DeleteWebhookResponse,
    DripConfig,
    EmitEventsBatchResult,
    EndRunResult,
    EventResult,
    HypotheticalUsageItem,
    ListChargesResponse,
    ListCustomersResponse,
    ListMetersResponse,
    ListWebhooksResponse,
    Meter,
    ListWorkflowsResponse,
    RecordRunResult,
    RetryOptions,
    RotateWebhookSecretResponse,
    RunResult,
    RunTimeline,
    TestWebhookResponse,
    TimelineEvent,
    TimelineRunInfo,
    TimelineTotals,
    TrackUsageResult,
    Webhook,
    Workflow,
    WrapApiCallResult,
)
from .resilience import (
    ResilienceConfig,
    ResilienceManager,
)
from .stream import StreamMeter, StreamMeterOptions
from .utils import generate_idempotency_key, verify_webhook_signature

logger = logging.getLogger("drip.client")

# Type variable for generic wrap_api_call
T = TypeVar("T")

# Default retry configuration
DEFAULT_RETRY_CONFIG = RetryOptions(max_attempts=3, base_delay_ms=100, max_delay_ms=5000)


def _is_retryable_error(error: Exception) -> bool:
    """Determine if an error is retryable."""
    # Check for network errors
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
        return True

    # Check for DripError with retryable status codes
    if hasattr(error, "status_code"):
        status_code = error.status_code
        # Retry on 5xx, 408 (timeout), 429 (rate limit)
        return status_code >= 500 or status_code == 408 or status_code == 429

    return False


# Thread-safe atomic counter for idempotency key generation.
# Each SDK call gets a unique counter value, ensuring that two rapid calls
# with identical parameters produce different keys. Retries still work
# because the key is generated once per SDK method call and reused across retries.
_call_counter_lock = threading.Lock()
_call_counter = 0


def _deterministic_idempotency_key(prefix: str, *components: str | float | None) -> str:
    """Generate a deterministic, unique idempotency key for each SDK call.

    Combines call parameters with a monotonic counter to produce keys that are:
    - **Unique per call**: Two rapid calls with identical params get different keys.
    - **Stable across retries**: Generated once per SDK method invocation.
    - **Deterministic**: No randomness — reproducible for debugging.

    To override, pass an explicit ``idempotency_key`` to any SDK method.
    """
    import hashlib

    global _call_counter  # noqa: PLW0603
    with _call_counter_lock:
        _call_counter += 1
        seq = _call_counter

    parts = [str(c) for c in components if c is not None]
    parts.append(str(seq))
    key_input = "|".join(parts)
    hash_hex = hashlib.sha256(key_input.encode()).hexdigest()[:24]
    return f"{prefix}_{hash_hex}"


def _retry_with_backoff_sync(
    fn: Callable[[], T],
    options: RetryOptions | None = None,
) -> T:
    """Execute a function with exponential backoff retry (synchronous)."""
    opts = options or DEFAULT_RETRY_CONFIG
    max_attempts = opts.max_attempts
    base_delay_ms = opts.base_delay_ms
    max_delay_ms = opts.max_delay_ms

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as error:
            last_error = error

            # Don't retry on last attempt or non-retryable errors
            if attempt == max_attempts or not _is_retryable_error(error):
                raise

            # Exponential backoff with jitter
            delay_ms = min(
                base_delay_ms * (2 ** (attempt - 1)) + random.random() * 100,
                max_delay_ms,
            )
            time.sleep(delay_ms / 1000)

    # Should never reach here, but needed for type checker
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected state in retry logic")


async def _retry_with_backoff_async(
    fn: Callable[[], Any],
    options: RetryOptions | None = None,
) -> Any:
    """Execute an async function with exponential backoff retry."""
    opts = options or DEFAULT_RETRY_CONFIG
    max_attempts = opts.max_attempts
    base_delay_ms = opts.base_delay_ms
    max_delay_ms = opts.max_delay_ms

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as error:
            last_error = error

            # Don't retry on last attempt or non-retryable errors
            if attempt == max_attempts or not _is_retryable_error(error):
                raise

            # Exponential backoff with jitter
            delay_ms = min(
                base_delay_ms * (2 ** (attempt - 1)) + random.random() * 100,
                max_delay_ms,
            )
            await asyncio.sleep(delay_ms / 1000)

    # Should never reach here, but needed for type checker
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected state in retry logic")


class Drip:
    """
    Official Python SDK client for Drip - usage-based billing with on-chain settlement.

    The Drip client provides methods for:
    - Customer management (create, list, get balance)
    - Charging (create charges, check status)
    - Checkout (fiat on-ramp)
    - Webhooks (create, manage, verify)
    - Agent run tracking (workflows, runs, events)
    - Meters (pricing configuration)

    Example:
        >>> from drip import Drip
        >>>
        >>> client = Drip(api_key="drip_sk_...")
        >>>
        >>> # Create a customer
        >>> customer = client.create_customer(
        ...     onchain_address="0x123...",
        ...     external_customer_id="user_123"
        ... )
        >>>
        >>> # Create a charge
        >>> result = client.charge(
        ...     customer_id=customer.id,
        ...     meter="api_calls",
        ...     quantity=1
        ... )
    """

    DEFAULT_BASE_URL = "https://drip-app-hlunj.ondigitalocean.app/v1"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        resilience: bool | ResilienceConfig | None = None,
    ) -> None:
        """
        Initialize the Drip client.

        Args:
            api_key: API key from Drip dashboard. If not provided,
                     reads from DRIP_API_KEY environment variable.
            base_url: Base URL for the API. Defaults to https://drip-app-hlunj.ondigitalocean.app/v1.
                      Can also be set via DRIP_API_URL environment variable.
            timeout: Request timeout in seconds. Defaults to 30.
            resilience: Enable production resilience features (rate limiting,
                       retry with backoff, circuit breaker, metrics).
                       - True: Use default production settings
                       - ResilienceConfig: Use custom configuration
                       - None/False: Disabled (default for backward compatibility)

        Raises:
            DripAuthenticationError: If no API key is provided or found in environment.

        Example:
            >>> # Basic usage
            >>> client = Drip(api_key="drip_sk_...")
            >>>
            >>> # With production resilience (recommended)
            >>> client = Drip(api_key="drip_sk_...", resilience=True)
            >>>
            >>> # With custom resilience settings
            >>> client = Drip(
            ...     api_key="drip_sk_...",
            ...     resilience=ResilienceConfig.high_throughput()
            ... )
        """
        self._api_key = api_key or os.environ.get("DRIP_API_KEY")
        if not self._api_key:
            raise DripAuthenticationError(
                "API key is required. Pass it directly or set DRIP_API_KEY environment variable."
            )

        self._base_url = (
            base_url or os.environ.get("DRIP_API_URL") or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout or self.DEFAULT_TIMEOUT

        # Setup resilience manager
        if resilience is True:
            self._resilience = ResilienceManager(ResilienceConfig.default())
        elif isinstance(resilience, ResilienceConfig):
            self._resilience = ResilienceManager(resilience)
        else:
            self._resilience = None

        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "drip-sdk-python/1.0.7",
            },
        )

    def __enter__(self) -> Drip:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        self._client.close()

    @property
    def config(self) -> DripConfig:
        """Get the current configuration."""
        # api_key is guaranteed to be non-None after __init__
        assert self._api_key is not None
        return DripConfig(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    @property
    def resilience(self) -> ResilienceManager | None:
        """Get the resilience manager (if enabled)."""
        return self._resilience

    def get_metrics(self) -> dict[str, Any] | None:
        """
        Get SDK metrics (requires resilience=True).

        Returns:
            Metrics summary including success rate, latencies, errors.
            None if resilience is not enabled.

        Example:
            >>> client = Drip(api_key="...", resilience=True)
            >>> # ... make some requests ...
            >>> metrics = client.get_metrics()
            >>> print(f"Success rate: {metrics['success_rate']}%")
            >>> print(f"P95 latency: {metrics['p95_latency_ms']}ms")
        """
        if self._resilience:
            return self._resilience.get_metrics()
        return None

    def get_health(self) -> dict[str, Any] | None:
        """
        Get SDK health status (requires resilience=True).

        Returns:
            Health status including circuit breaker state, rate limiter status.
            None if resilience is not enabled.

        Example:
            >>> client = Drip(api_key="...", resilience=True)
            >>> health = client.get_health()
            >>> print(f"Circuit: {health['circuit_breaker']['state']}")
        """
        if self._resilience:
            return self._resilience.get_health()
        return None

    # =========================================================================
    # Health Check
    # =========================================================================

    def ping(self) -> dict[str, Any]:
        """
        Ping the Drip API to check connectivity and measure latency.

        Returns:
            Dict with ok (bool), status (str), latency_ms (int), and timestamp.

        Example:
            >>> health = client.ping()
            >>> if health["ok"]:
            ...     print(f"API healthy, latency: {health['latency_ms']}ms")
        """
        import time

        # Construct health endpoint URL (without /v1)
        health_url = self._base_url
        if health_url.endswith("/v1"):
            health_url = health_url[:-3]
        elif health_url.endswith("/v1/"):
            health_url = health_url[:-4]
        health_url = health_url.rstrip("/") + "/health"

        start = time.time()
        try:
            response = self._client.get(health_url)
            latency_ms = int((time.time() - start) * 1000)

            try:
                data = response.json()
                status = data.get("status", "unknown")
                timestamp = data.get("timestamp", int(time.time()))
            except Exception:
                status = "healthy" if response.is_success else f"error:{response.status_code}"
                timestamp = int(time.time())

            return {
                "ok": response.is_success and status == "healthy",
                "status": status,
                "latency_ms": latency_ms,
                "timestamp": timestamp,
            }
        except httpx.RequestError as e:
            raise DripNetworkError(f"Ping failed: {e}") from e

    # =========================================================================
    # HTTP Request Helpers
    # =========================================================================

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API endpoint path.
            json: JSON body for POST/PUT requests.
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            DripAPIError: For API errors.
            DripNetworkError: For network errors.
        """
        if self._resilience:
            return self._resilience.execute(
                lambda: self._raw_request(method, path, json, params),
                method=method,
                endpoint=path,
            )
        return self._raw_request(method, path, json, params)

    def _raw_request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the actual HTTP request (internal)."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "drip request: %s %s body=%s params=%s",
                method,
                path,
                _json_mod.dumps(json, default=str) if json else None,
                _json_mod.dumps(params, default=str) if params else None,
            )
        try:
            response = self._client.request(
                method=method,
                url=path,
                json=json,
                params=params,
            )
        except httpx.TimeoutException as e:
            raise DripNetworkError(f"Request timed out: {path}", original_error=e) from e
        except httpx.RequestError as e:
            raise DripNetworkError(f"Network error: {e}", original_error=e) from e

        # Handle error responses
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {"error": response.text or "Unknown error"}

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "drip response: %s %s status=%d body=%s",
                    method,
                    path,
                    response.status_code,
                    _json_mod.dumps(body, default=str),
                )

            error = create_api_error_from_response(response.status_code, body)
            # Add status_code for resilience retry logic
            error.status_code = response.status_code  # type: ignore[attr-defined]
            raise error

        # Parse successful response
        if response.status_code == 204:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("drip response: %s %s status=204 body={}", method, path)
            return {}

        try:
            result: dict[str, Any] = response.json()
        except Exception:
            result = {}

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "drip response: %s %s status=%d body=%s",
                method,
                path,
                response.status_code,
                _json_mod.dumps(result, default=str),
            )

        return result

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request."""
        return self._request("GET", path, params=params)

    def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        return self._request("POST", path, json=json)

    def _put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PUT request."""
        return self._request("PUT", path, json=json)

    def _patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PATCH request."""
        return self._request("PATCH", path, json=json)

    def _delete(self, path: str) -> dict[str, Any]:
        """Make a DELETE request."""
        return self._request("DELETE", path)

    # =========================================================================
    # Customer Management
    # =========================================================================

    def create_customer(
        self,
        onchain_address: str | None = None,
        external_customer_id: str | None = None,
        is_internal: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        """
        Create a new customer.

        At least one of ``onchain_address`` or ``external_customer_id`` is required.

        Args:
            onchain_address: Customer's smart account address (optional).
            external_customer_id: Your internal customer ID (optional).
            is_internal: Mark as internal/non-billing customer (optional, defaults to False).
            metadata: Custom metadata.

        Returns:
            The created Customer object.

        Raises:
            DripAPIError: If neither onchain_address nor external_customer_id is provided.
        """
        body: dict[str, Any] = {}

        if onchain_address:
            body["onchainAddress"] = onchain_address
        if external_customer_id:
            body["externalCustomerId"] = external_customer_id
        if is_internal is not None:
            body["isInternal"] = is_internal
        if metadata:
            body["metadata"] = metadata

        response = self._post("/customers", json=body)
        return Customer.model_validate(response)

    def get_customer(self, customer_id: str) -> Customer:
        """
        Get a customer by ID.

        Args:
            customer_id: The customer ID.

        Returns:
            The Customer object.
        """
        response = self._get(f"/customers/{customer_id}")
        return Customer.model_validate(response)

    def list_customers(
        self,
        status: CustomerStatus | None = None,
        limit: int = 100,
    ) -> ListCustomersResponse:
        """
        List customers with optional filtering.

        Args:
            status: Filter by status (ACTIVE, LOW_BALANCE, PAUSED).
            limit: Maximum number of results (1-100).

        Returns:
            List of customers with count.
        """
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status.value

        response = self._get("/customers", params=params)
        return ListCustomersResponse.model_validate(response)

    def get_balance(self, customer_id: str) -> BalanceResult:
        """
        Get a customer's current balance.

        Args:
            customer_id: The customer ID.

        Returns:
            Balance information including USDC and native token balances.
        """
        response = self._get(f"/customers/{customer_id}/balance")
        return BalanceResult.model_validate(response)

    # =========================================================================
    # Charging & Usage
    # =========================================================================

    def charge(
        self,
        customer_id: str,
        meter: str,
        quantity: float,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChargeResult:
        """
        Create a charge for usage.

        This is the primary billing method. It records usage and charges
        the customer's account.

        Args:
            customer_id: The customer ID.
            meter: Usage meter type (e.g., "api_calls", "tokens").
            quantity: Amount to charge.
            idempotency_key: Optional key to prevent duplicate charges.
            metadata: Optional metadata.

        Returns:
            ChargeResult with charge details and transaction hash.
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "usageType": meter,
            "quantity": quantity,
        }

        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "chg", customer_id, meter, quantity
        )
        if metadata:
            body["metadata"] = metadata

        response = self._post("/usage", json=body)
        return ChargeResult.model_validate(response)

    def get_charge(self, charge_id: str) -> Charge:
        """
        Get detailed charge information.

        Args:
            charge_id: The charge ID.

        Returns:
            Full Charge object with customer and usage event details.
        """
        response = self._get(f"/charges/{charge_id}")
        return Charge.model_validate(response)

    def list_charges(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> ListChargesResponse:
        """
        List charges with optional filtering.

        Args:
            customer_id: Filter by customer.
            status: Filter by status.
            limit: Maximum results (1-100).

        Returns:
            List of charges with count.
        """
        params: dict[str, Any] = {"limit": limit}
        if customer_id:
            params["customerId"] = customer_id
        if status:
            params["status"] = status

        response = self._get("/charges", params=params)
        return ListChargesResponse.model_validate(response)

    def get_charge_status(self, charge_id: str) -> ChargeStatusResult:
        """
        Quick status check for a charge.

        Args:
            charge_id: The charge ID.

        Returns:
            Status and optional transaction hash.
        """
        response = self._get(f"/charges/{charge_id}/status")
        return ChargeStatusResult.model_validate(response)

    def track_usage(
        self,
        customer_id: str,
        meter: str,
        quantity: float,
        idempotency_key: str | None = None,
        units: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrackUsageResult:
        """
        Record usage for internal visibility WITHOUT billing.

        Use this for:
        - Tracking internal team usage without charging
        - Pilot programs where you want visibility before billing
        - Pre-billing tracking before customer wallet setup

        This does NOT:
        - Create a Charge record
        - Require customer balance
        - Require blockchain/wallet setup

        For billing, use `charge()` instead.

        Args:
            customer_id: The customer ID.
            meter: Usage meter type (e.g., "api_calls", "tokens").
            quantity: Amount to record.
            idempotency_key: Optional key to prevent duplicate records.
            units: Optional unit label (e.g., "tokens", "requests").
            description: Optional description.
            metadata: Optional metadata.

        Returns:
            TrackUsageResult with event ID and confirmation.
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "usageType": meter,
            "quantity": quantity,
        }

        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "track", customer_id, meter, quantity
        )
        if units:
            body["units"] = units
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata

        response = self._post("/usage/internal", json=body)
        return TrackUsageResult.model_validate(response)

    def wrap_api_call(
        self,
        customer_id: str,
        meter: str,
        call: Callable[[], T],
        extract_usage: Callable[[T], float],
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        retry_options: RetryOptions | None = None,
    ) -> WrapApiCallResult:
        """
        Wraps an external API call with guaranteed usage recording.

        This solves the crash-before-record problem:

        DANGEROUS - usage lost if crash between lines 1 and 2:
        >>> response = openai.chat.completions.create(...)  # line 1
        >>> client.charge(customer_id, "tokens", response.usage.total_tokens)  # line 2

        SAFE - wrap_api_call guarantees recording with retry:
        >>> result = client.wrap_api_call(
        ...     customer_id="cust_123",
        ...     meter="tokens",
        ...     call=lambda: openai.chat.completions.create(...),
        ...     extract_usage=lambda r: r.usage.total_tokens,
        ... )

        How it works:
        1. Generates idempotency key BEFORE the API call
        2. Makes the external API call (once, no retry)
        3. Records usage in Drip with retry + idempotency
        4. If recording fails transiently, retries are safe (no double-charge)

        Args:
            customer_id: The Drip customer ID to charge.
            meter: The usage meter/type to record against.
            call: The function that makes the external API call.
            extract_usage: Function to extract usage quantity from the API result.
            idempotency_key: Custom idempotency key prefix (auto-generated if not provided).
            metadata: Optional metadata to attach to the charge.
            retry_options: Custom retry options for the charge call.

        Returns:
            WrapApiCallResult containing the API result, charge result, and idempotency key.

        Raises:
            DripAPIError: If the Drip charge fails after retries.
            Exception: If the external API call fails (no retry).

        Example:
            >>> # OpenAI example
            >>> result = client.wrap_api_call(
            ...     customer_id="cust_abc123",
            ...     meter="tokens",
            ...     call=lambda: openai.chat.completions.create(
            ...         model="gpt-4",
            ...         messages=[{"role": "user", "content": "Hello!"}],
            ...     ),
            ...     extract_usage=lambda r: r.usage.total_tokens if r.usage else 0,
            ... )
            >>> print(result.result.choices[0].message.content)
            >>> print(f"Charged: {result.charge.charge.amount_usdc} USDC")

            >>> # Anthropic example
            >>> result = client.wrap_api_call(
            ...     customer_id="cust_abc123",
            ...     meter="tokens",
            ...     call=lambda: anthropic.messages.create(
            ...         model="claude-3-opus-20240229",
            ...         max_tokens=1024,
            ...         messages=[{"role": "user", "content": "Hello!"}],
            ...     ),
            ...     extract_usage=lambda r: r.usage.input_tokens + r.usage.output_tokens,
            ... )
        """
        # Generate idempotency key BEFORE the call - this is the key insight!
        # Even if we crash after the API call, retrying with the same key is safe.
        key = idempotency_key or f"wrap_{int(time.time() * 1000)}_{random.randbytes(8).hex()[:9]}"

        # Step 1: Make the external API call (no retry - we don't control this)
        result = call()

        # Step 2: Extract usage from the result
        quantity = extract_usage(result)

        # Step 3: Record usage in Drip with retry (idempotency makes this safe)
        charge = _retry_with_backoff_sync(
            lambda: self.charge(
                customer_id=customer_id,
                meter=meter,
                quantity=quantity,
                idempotency_key=key,
                metadata=metadata,
            ),
            retry_options,
        )

        return WrapApiCallResult(
            result=result,
            charge=charge,
            idempotency_key=key,
        )

    # =========================================================================
    # Cost Estimation
    # =========================================================================

    def estimate_from_usage(
        self,
        period_start: datetime | str,
        period_end: datetime | str,
        customer_id: str | None = None,
        default_unit_price: str | None = None,
        include_charged_events: bool | None = None,
        usage_types: list[str] | None = None,
        custom_pricing: dict[str, str] | None = None,
    ) -> CostEstimateResponse:
        """
        Estimates costs from historical usage events.

        Use this to preview what existing usage would cost before creating charges,
        or to run "what-if" scenarios with custom pricing.

        Args:
            period_start: Start of the period to estimate (datetime or ISO string).
            period_end: End of the period to estimate (datetime or ISO string).
            customer_id: Filter to a specific customer (optional).
            default_unit_price: Default price for usage types without pricing plans.
            include_charged_events: Include events that already have charges (default: True).
            usage_types: Filter to specific usage types.
            custom_pricing: Custom pricing overrides (takes precedence over DB pricing).

        Returns:
            CostEstimateResponse with line item breakdown.

        Example:
            >>> # Estimate costs for last month's usage
            >>> estimate = client.estimate_from_usage(
            ...     period_start=datetime(2024, 1, 1),
            ...     period_end=datetime(2024, 1, 31),
            ... )
            >>> print(f"Estimated total: ${estimate.estimated_total_usdc}")

            >>> # "What-if" scenario with custom pricing
            >>> estimate = client.estimate_from_usage(
            ...     period_start="2024-01-01T00:00:00Z",
            ...     period_end="2024-01-31T23:59:59Z",
            ...     custom_pricing={
            ...         "api_call": "0.005",  # What if we charged $0.005 per call?
            ...         "token": "0.0001",    # What if we charged $0.0001 per token?
            ...     },
            ... )
        """
        # Convert datetime to ISO string if needed
        start_str = period_start.isoformat() if isinstance(period_start, datetime) else period_start
        end_str = period_end.isoformat() if isinstance(period_end, datetime) else period_end

        body: dict[str, Any] = {
            "periodStart": start_str,
            "periodEnd": end_str,
        }

        if customer_id is not None:
            body["customerId"] = customer_id
        if default_unit_price is not None:
            body["defaultUnitPrice"] = default_unit_price
        if include_charged_events is not None:
            body["includeChargedEvents"] = include_charged_events
        if usage_types is not None:
            body["usageTypes"] = usage_types
        if custom_pricing is not None:
            body["customPricing"] = custom_pricing

        response = self._post("/dashboard/cost-estimate/from-usage", json=body)
        return CostEstimateResponse.model_validate(response)

    def estimate_from_hypothetical(
        self,
        items: list[HypotheticalUsageItem] | list[dict[str, Any]],
        default_unit_price: str | None = None,
        custom_pricing: dict[str, str] | None = None,
    ) -> CostEstimateResponse:
        """
        Estimates costs from hypothetical usage.

        Use this for "what-if" scenarios, budget planning, or to preview
        costs before usage occurs.

        Args:
            items: List of usage items to estimate. Each item should have:
                - usage_type (or usageType): The usage type (e.g., "api_call", "token")
                - quantity: The quantity of usage
                - unit_price_override (optional): Override unit price for this item
            default_unit_price: Default price for usage types without pricing plans.
            custom_pricing: Custom pricing overrides (takes precedence over DB pricing).

        Returns:
            CostEstimateResponse with line item breakdown.

        Example:
            >>> # Estimate what 10,000 API calls and 1M tokens would cost
            >>> estimate = client.estimate_from_hypothetical(
            ...     items=[
            ...         HypotheticalUsageItem(usage_type="api_call", quantity=10000),
            ...         HypotheticalUsageItem(usage_type="token", quantity=1000000),
            ...     ],
            ... )
            >>> print(f"Estimated total: ${estimate.estimated_total_usdc}")
            >>> for item in estimate.line_items:
            ...     print(f"  {item.usage_type}: {item.quantity} × ${item.unit_price} = ${item.estimated_cost_usdc}")

            >>> # Using dicts instead of models
            >>> estimate = client.estimate_from_hypothetical(
            ...     items=[
            ...         {"usageType": "api_call", "quantity": 10000},
            ...         {"usageType": "token", "quantity": 1000000},
            ...     ],
            ... )

            >>> # Compare different pricing scenarios
            >>> current = client.estimate_from_hypothetical(
            ...     items=[{"usageType": "api_call", "quantity": 100000}],
            ... )
            >>> discounted = client.estimate_from_hypothetical(
            ...     items=[{"usageType": "api_call", "quantity": 100000}],
            ...     custom_pricing={"api_call": "0.0005"},  # 50% discount
            ... )
            >>> print(f"Current: ${current.estimated_total_usdc}")
            >>> print(f"With 50% discount: ${discounted.estimated_total_usdc}")
        """
        # Convert items to dicts if they're Pydantic models
        items_data: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, HypotheticalUsageItem):
                items_data.append(item.model_dump(by_alias=True, exclude_none=True))
            else:
                items_data.append(item)

        body: dict[str, Any] = {"items": items_data}

        if default_unit_price is not None:
            body["defaultUnitPrice"] = default_unit_price
        if custom_pricing is not None:
            body["customPricing"] = custom_pricing

        response = self._post("/dashboard/cost-estimate/hypothetical", json=body)
        return CostEstimateResponse.model_validate(response)

    # =========================================================================
    # Checkout (Fiat On-Ramp)
    # =========================================================================

    def checkout(
        self,
        amount: int,
        return_url: str,
        customer_id: str | None = None,
        external_customer_id: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutResult:
        """
        Create a checkout session for customers to add funds.

        This is the primary method for getting money into Drip accounts.
        Supports ACH, debit card, and direct USDC.

        Args:
            amount: Amount in cents (5000 = $50.00).
            return_url: Redirect URL after successful payment.
            customer_id: Optional existing customer ID.
            external_customer_id: For new customers (your internal ID).
            cancel_url: Optional redirect URL on cancellation.
            metadata: Optional metadata.

        Returns:
            CheckoutResult with hosted checkout URL.
        """
        body: dict[str, Any] = {
            "amount": amount,
            "returnUrl": return_url,
        }

        if customer_id:
            body["customerId"] = customer_id
        if external_customer_id:
            body["externalCustomerId"] = external_customer_id
        if cancel_url:
            body["cancelUrl"] = cancel_url
        if metadata:
            body["metadata"] = metadata

        response = self._post("/checkout", json=body)
        return CheckoutResult.model_validate(response)

    # =========================================================================
    # Webhooks
    # =========================================================================

    def create_webhook(
        self,
        url: str,
        events: list[str],
        description: str | None = None,
    ) -> CreateWebhookResponse:
        """
        Create a webhook endpoint.

        IMPORTANT: The secret is returned only once - store it securely!

        Args:
            url: HTTPS endpoint URL.
            events: List of event types to subscribe to.
            description: Optional description.

        Returns:
            Webhook with secret (store the secret securely!).
        """
        body: dict[str, Any] = {
            "url": url,
            "events": events,
        }

        if description:
            body["description"] = description

        response = self._post("/webhooks", json=body)
        return CreateWebhookResponse.model_validate(response)

    def list_webhooks(self) -> ListWebhooksResponse:
        """
        List all webhooks with delivery statistics.

        Returns:
            List of webhooks with stats.
        """
        response = self._get("/webhooks")
        return ListWebhooksResponse.model_validate(response)

    def get_webhook(self, webhook_id: str) -> Webhook:
        """
        Get a specific webhook.

        Args:
            webhook_id: The webhook ID.

        Returns:
            Webhook details.
        """
        response = self._get(f"/webhooks/{webhook_id}")
        return Webhook.model_validate(response)

    def delete_webhook(self, webhook_id: str) -> DeleteWebhookResponse:
        """
        Delete a webhook.

        Args:
            webhook_id: The webhook ID.

        Returns:
            Deletion confirmation.
        """
        response = self._delete(f"/webhooks/{webhook_id}")
        return DeleteWebhookResponse.model_validate(response)

    def test_webhook(self, webhook_id: str) -> TestWebhookResponse:
        """
        Send a test event to a webhook.

        Args:
            webhook_id: The webhook ID.

        Returns:
            Test result with delivery ID.
        """
        response = self._post(f"/webhooks/{webhook_id}/test")
        return TestWebhookResponse.model_validate(response)

    def rotate_webhook_secret(self, webhook_id: str) -> RotateWebhookSecretResponse:
        """
        Generate a new webhook secret.

        Args:
            webhook_id: The webhook ID.

        Returns:
            New secret (store securely!).
        """
        response = self._post(f"/webhooks/{webhook_id}/rotate-secret")
        return RotateWebhookSecretResponse.model_validate(response)

    # =========================================================================
    # Workflows
    # =========================================================================

    def create_workflow(
        self,
        name: str,
        slug: str,
        product_surface: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        """
        Create a workflow definition for tracking agent runs.

        Args:
            name: Human-readable workflow name.
            slug: URL-safe identifier.
            product_surface: Type (RPC, WEBHOOK, AGENT, PIPELINE, CUSTOM).
            description: Optional description.
            metadata: Optional metadata.

        Returns:
            Created Workflow.
        """
        body: dict[str, Any] = {
            "name": name,
            "slug": slug,
        }

        if product_surface:
            body["productSurface"] = product_surface
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata

        response = self._post("/workflows", json=body)
        return Workflow.model_validate(response)

    def list_workflows(self) -> ListWorkflowsResponse:
        """
        List all workflows.

        Returns:
            List of workflows with count.
        """
        response = self._get("/workflows")
        return ListWorkflowsResponse.model_validate(response)

    # =========================================================================
    # Agent Runs
    # =========================================================================

    def start_run(
        self,
        customer_id: str,
        workflow_id: str,
        external_run_id: str | None = None,
        correlation_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunResult:
        """
        Start a new agent run.

        Args:
            customer_id: The customer ID.
            workflow_id: The workflow ID.
            external_run_id: Your internal run ID.
            correlation_id: For distributed tracing.
            parent_run_id: For nested runs.
            metadata: Optional metadata.

        Returns:
            RunResult with run ID and status.
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "workflowId": workflow_id,
        }

        if external_run_id:
            body["externalRunId"] = external_run_id
        if correlation_id:
            body["correlationId"] = correlation_id
        if parent_run_id:
            body["parentRunId"] = parent_run_id
        if metadata:
            body["metadata"] = metadata

        response = self._post("/runs", json=body)
        return RunResult.model_validate(response)

    def end_run(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EndRunResult:
        """
        End an agent run.

        Args:
            run_id: The run ID.
            status: Final status (COMPLETED, FAILED, CANCELLED, TIMEOUT).
            error_message: Optional error message for failed runs.
            error_code: Optional error code.
            metadata: Optional metadata.

        Returns:
            EndRunResult with final status and totals.
        """
        body: dict[str, Any] = {"status": status}

        if error_message:
            body["errorMessage"] = error_message
        if error_code:
            body["errorCode"] = error_code
        if metadata:
            body["metadata"] = metadata

        response = self._patch(f"/runs/{run_id}", json=body)
        return EndRunResult.model_validate(response)

    def emit_event(
        self,
        run_id: str,
        event_type: str,
        quantity: float | None = None,
        units: str | None = None,
        description: str | None = None,
        cost_units: float | None = None,
        cost_currency: str | None = None,
        correlation_id: str | None = None,
        parent_event_id: str | None = None,
        span_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EventResult:
        """
        Emit an event within a run.

        Args:
            run_id: The run ID.
            event_type: Event type (e.g., "agent.step", "tool.call").
            quantity: Optional quantity.
            units: Unit label (e.g., "tokens", "pages").
            description: Optional description.
            cost_units: Optional cost in units.
            cost_currency: Cost currency.
            correlation_id: For distributed tracing.
            parent_event_id: For nested events.
            span_id: OpenTelemetry span ID.
            idempotency_key: Prevent duplicate events.
            metadata: Optional metadata.

        Returns:
            EventResult with event ID and duplicate status.
        """
        body: dict[str, Any] = {
            "runId": run_id,
            "eventType": event_type,
        }

        if quantity is not None:
            body["quantity"] = quantity
        if units:
            body["units"] = units
        if description:
            body["description"] = description
        if cost_units is not None:
            body["costUnits"] = cost_units
        if cost_currency:
            body["costCurrency"] = cost_currency
        if correlation_id:
            body["correlationId"] = correlation_id
        if parent_event_id:
            body["parentEventId"] = parent_event_id
        if span_id:
            body["spanId"] = span_id
        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "evt", run_id, event_type, quantity
        )
        if metadata:
            body["metadata"] = metadata

        response = self._post("/run-events", json=body)
        return EventResult.model_validate(response)

    def emit_events_batch(
        self,
        events: list[dict[str, Any]],
    ) -> EmitEventsBatchResult:
        """
        Emit multiple events in one request.

        Args:
            events: List of event objects with runId, eventType, etc.

        Returns:
            Batch result with created count and duplicates.
        """
        response = self._post("/run-events/batch", json={"events": events})
        return EmitEventsBatchResult.model_validate(response)

    def get_run_timeline(self, run_id: str) -> RunTimeline:
        """
        Get the full timeline for a run.

        Args:
            run_id: The run ID.

        Returns:
            RunTimeline with events and computed totals.
        """
        data = self._get(f"/runs/{run_id}/timeline")

        # Build run info from the flat timeline response
        run = TimelineRunInfo(
            id=data.get("runId", run_id),
            customerId=data.get("customerId", ""),
            customerName=data.get("customerName"),
            workflowId=data.get("workflowId", ""),
            workflowName=data.get("workflowName", ""),
            status=data.get("status", "RUNNING"),
            startedAt=data.get("startedAt"),
            endedAt=data.get("endedAt"),
            durationMs=data.get("durationMs"),
            errorMessage=data.get("errorMessage"),
            errorCode=data.get("errorCode"),
            correlationId=data.get("correlationId"),
            metadata=data.get("metadata"),
        )

        # Map events from the V2 timeline format
        events_data = data.get("events", [])
        timeline = []
        for e in events_data:
            meta = e.get("metadata", {}) if isinstance(e.get("metadata"), dict) else {}
            timeline.append(TimelineEvent(
                id=e["id"],
                eventType=e.get("eventType", e.get("actionName", "")),
                quantity=meta.get("quantity", 0) if isinstance(meta, dict) else 0,
                units=meta.get("units") if isinstance(meta, dict) else None,
                description=e.get("description", e.get("explanation")),
                costUnits=e.get("costUsdc"),
                timestamp=e.get("timestamp", e.get("createdAt", "")),
                correlationId=e.get("correlationId"),
                parentEventId=e.get("parentEventId"),
            ))

        # Build totals from the summary object
        summary_data = data.get("summary", {})
        totals = TimelineTotals(
            eventCount=summary_data.get("totalEvents", len(events_data)) if isinstance(summary_data, dict) else len(events_data),
            totalQuantity=str(summary_data.get("totalQuantity", "0")) if isinstance(summary_data, dict) else "0",
            totalCostUnits=str(summary_data.get("totalCostUnits", "0")) if isinstance(summary_data, dict) else "0",
            totalChargedUsdc=str(summary_data.get("totalChargedUsdc", "0")) if isinstance(summary_data, dict) else "0",
        )

        summary_str = ""
        if isinstance(summary_data, dict):
            summary_str = f"{summary_data.get('totalEvents', len(events_data))} events"
        elif isinstance(summary_data, str):
            summary_str = summary_data

        return RunTimeline(
            run=run,
            timeline=timeline,
            totals=totals,
            summary=summary_str,
        )

    # =========================================================================
    # Simplified API: Record Run
    # =========================================================================

    def record_run(
        self,
        customer_id: str,
        workflow: str,
        events: list[dict[str, Any]],
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
        external_run_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecordRunResult:
        """
        One-call simplified API for recording a complete agent run.

        Server-side endpoint handles workflow resolution, run creation,
        event emission, and run completion atomically.

        Args:
            customer_id: The customer ID.
            workflow: Workflow ID or slug (auto-creates if slug).
            events: List of events with eventType, quantity, etc.
            status: Final status (COMPLETED, FAILED, CANCELLED, TIMEOUT).
            error_message: Optional error message.
            error_code: Optional error code.
            external_run_id: Your internal run ID.
            correlation_id: For distributed tracing.
            metadata: Optional metadata.

        Returns:
            RecordRunResult with run info and event stats.
        """
        # Normalize event keys: accept both snake_case and camelCase
        normalized_events: list[dict[str, Any]] = []
        for event in events:
            evt: dict[str, Any] = {
                "eventType": event.get("event_type", event.get("eventType", "")),
            }
            if "quantity" in event:
                evt["quantity"] = event["quantity"]
            for key in ("units", "description", "metadata"):
                if event.get(key) is not None:
                    evt[key] = event[key]
            cost = event.get("cost_units", event.get("costUnits"))
            if cost is not None:
                evt["costUnits"] = cost
            normalized_events.append(evt)

        body: dict[str, Any] = {
            "customerId": customer_id,
            "workflow": workflow,
            "events": normalized_events,
            "status": status,
        }
        if error_message:
            body["errorMessage"] = error_message
        if error_code:
            body["errorCode"] = error_code
        if external_run_id:
            body["externalRunId"] = external_run_id
        if correlation_id:
            body["correlationId"] = correlation_id
        if metadata:
            body["metadata"] = metadata

        # Try single-call endpoint; fall back to 4-step if server returns 404
        try:
            data = self._post("/runs/record", json=body)
            return RecordRunResult.model_validate(data)
        except DripError as e:
            if e.status_code != 404:
                raise

        return self._record_run_fallback(
            customer_id, workflow, normalized_events, status,
            error_message, error_code, external_run_id, correlation_id, metadata,
        )

    def _record_run_fallback(
        self,
        customer_id: str,
        workflow: str,
        events: list[dict[str, Any]],
        status: str,
        error_message: str | None,
        error_code: str | None,
        external_run_id: str | None,
        correlation_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> RecordRunResult:
        """4-step orchestration fallback for servers without POST /runs/record."""
        import time as _time

        start = _time.monotonic()

        # Step 1: Resolve workflow
        workflows_resp = self.list_workflows()
        match = next(
            (w for w in workflows_resp.data if w.slug == workflow or w.id == workflow),
            None,
        )
        if match:
            workflow_id = match.id
            workflow_name = match.name
        else:
            pretty = workflow.replace("_", " ").replace("-", " ").title()
            created = self._post("/workflows", json={
                "name": pretty, "slug": workflow, "productSurface": "CUSTOM",
            })
            workflow_id = created["id"]
            workflow_name = created["name"]

        # Step 2: Start run
        run = self.start_run(
            customer_id=customer_id,
            workflow_id=workflow_id,
            external_run_id=external_run_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )

        # Step 3: Emit events
        events_created = 0
        events_duplicates = 0
        if events:
            batch: list[dict[str, Any]] = []
            for i, evt in enumerate(events):
                entry: dict[str, Any] = {
                    "runId": run.id,
                    "eventType": evt["eventType"],
                    "quantity": evt.get("quantity", 1),
                }
                for key in ("units", "description", "costUnits", "metadata"):
                    if key in evt:
                        entry[key] = evt[key]
                if external_run_id:
                    entry["idempotencyKey"] = f"{external_run_id}:{evt['eventType']}:{i}"
                batch.append(entry)
            result = self.emit_events_batch(batch)
            events_created = result.created
            events_duplicates = result.duplicates

        # Step 4: End run
        end_result = self.end_run(
            run_id=run.id,
            status=status,
            error_message=error_message,
            error_code=error_code,
        )

        elapsed_ms = int((_time.monotonic() - start) * 1000)
        dur = end_result.duration_ms if end_result.duration_ms is not None else elapsed_ms
        icon = "\u2713" if status == "COMPLETED" else "\u2717" if status == "FAILED" else "\u25CB"

        return RecordRunResult.model_validate({
            "run": {
                "id": run.id,
                "workflowId": workflow_id,
                "workflowName": workflow_name,
                "status": end_result.status.value,
                "durationMs": dur,
            },
            "events": {"created": events_created, "duplicates": events_duplicates},
            "totalCostUnits": end_result.total_cost_units,
            "summary": f"{icon} {workflow_name}: {events_created} events recorded ({dur}ms)",
        })

    # =========================================================================
    # Meters
    # =========================================================================

    def list_meters(self) -> ListMetersResponse:
        """
        List available usage meters from pricing plans.

        Returns:
            List of meters with pricing information.
        """
        response = self._get("/pricing-plans")
        plans = response.get("data", [])
        return ListMetersResponse(
            data=[
                Meter(
                    id=p["id"],
                    name=p["name"],
                    meter=p["unitType"],
                    unitPriceUsd=p["unitPriceUsd"],
                    isActive=p["isActive"],
                )
                for p in plans
            ],
            count=response.get("count", len(plans)),
        )

    # =========================================================================
    # Static Utility Methods
    # =========================================================================

    @staticmethod
    def generate_idempotency_key(
        customer_id: str,
        step_name: str,
        run_id: str | None = None,
        sequence: int | None = None,
    ) -> str:
        """
        Generate a deterministic idempotency key.

        Ensures "one logical action = one event" even with retries.

        Args:
            customer_id: The customer ID.
            step_name: The name of the step/action.
            run_id: Optional run ID for scoping.
            sequence: Optional sequence number.

        Returns:
            Deterministic idempotency key.
        """
        return generate_idempotency_key(customer_id, step_name, run_id, sequence)

    @staticmethod
    def verify_webhook_signature(
        payload: str,
        signature: str,
        secret: str,
    ) -> bool:
        """
        Verify a webhook signature.

        Uses HMAC-SHA256 with timing-safe comparison.

        Args:
            payload: Raw request body as string.
            signature: X-Drip-Signature header value.
            secret: Webhook secret.

        Returns:
            True if signature is valid.
        """
        return verify_webhook_signature(payload, signature, secret)

    # =========================================================================
    # StreamMeter Factory
    # =========================================================================

    def create_stream_meter(
        self,
        customer_id: str,
        meter: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush_threshold: float | None = None,
        on_add: Any = None,
        on_flush: Any = None,
    ) -> StreamMeter:
        """
        Create a StreamMeter for accumulating usage and charging once.

        Perfect for LLM token streaming where you want to:
        - Accumulate tokens locally (no API call per token)
        - Charge once at the end of the stream
        - Handle partial failures (charge for what was delivered)

        Args:
            customer_id: The Drip customer ID to charge.
            meter: The usage meter/type to record against.
            idempotency_key: Optional base key for idempotent charges.
            metadata: Optional metadata to attach to the charge.
            flush_threshold: Optional auto-flush when quantity exceeds this.
            on_add: Optional callback(quantity, total) on each add.
            on_flush: Optional callback(result) after each flush.

        Returns:
            A new StreamMeter instance.

        Example:
            >>> meter = client.create_stream_meter(
            ...     customer_id="cust_abc123",
            ...     meter="tokens",
            ... )
            >>>
            >>> for chunk in llm_stream:
            ...     meter.add_sync(chunk.tokens)
            >>>
            >>> result = meter.flush()
            >>> print(f"Charged {result.charge.amount_usdc} for {result.quantity} tokens")
        """
        options = StreamMeterOptions(
            customer_id=customer_id,
            meter=meter,
            idempotency_key=idempotency_key,
            metadata=metadata,
            flush_threshold=flush_threshold,
            on_add=on_add,
            on_flush=on_flush,
        )
        return StreamMeter(_charge_fn=self.charge, _options=options)


class AsyncDrip:
    """
    Async version of the Drip client.

    Provides the same API as Drip but with async/await support.

    Example:
        >>> from drip import AsyncDrip
        >>>
        >>> async with AsyncDrip(api_key="drip_sk_...") as client:
        ...     customer = await client.create_customer(
        ...         onchain_address="0x123..."
        ...     )
    """

    DEFAULT_BASE_URL = "https://drip-app-hlunj.ondigitalocean.app/v1"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        resilience: bool | ResilienceConfig | None = None,
    ) -> None:
        """
        Initialize the async Drip client.

        Args:
            api_key: API key from Drip dashboard.
            base_url: Base URL for the API.
            timeout: Request timeout in seconds.
            resilience: Enable production resilience features (rate limiting,
                       retry with backoff, circuit breaker, metrics).
                       - True: Use default production settings
                       - ResilienceConfig: Use custom configuration
                       - None/False: Disabled (default for backward compatibility)

        Example:
            >>> # Basic usage
            >>> async with AsyncDrip(api_key="drip_sk_...") as client:
            ...     customer = await client.create_customer(...)
            >>>
            >>> # With production resilience (recommended)
            >>> async with AsyncDrip(api_key="drip_sk_...", resilience=True) as client:
            ...     customer = await client.create_customer(...)
        """
        self._api_key = api_key or os.environ.get("DRIP_API_KEY")
        if not self._api_key:
            raise DripAuthenticationError(
                "API key is required. Pass it directly or set DRIP_API_KEY environment variable."
            )

        self._base_url = (
            base_url or os.environ.get("DRIP_API_URL") or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout or self.DEFAULT_TIMEOUT

        # Setup resilience manager
        if resilience is True:
            self._resilience = ResilienceManager(ResilienceConfig.default())
        elif isinstance(resilience, ResilienceConfig):
            self._resilience = ResilienceManager(resilience)
        else:
            self._resilience = None

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "drip-sdk-python/1.0.7",
            },
        )

    async def __aenter__(self) -> AsyncDrip:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    @property
    def config(self) -> DripConfig:
        """Get the current configuration."""
        # api_key is guaranteed to be non-None after __init__
        assert self._api_key is not None
        return DripConfig(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    @property
    def resilience(self) -> ResilienceManager | None:
        """Get the resilience manager (if enabled)."""
        return self._resilience

    def get_metrics(self) -> dict[str, Any] | None:
        """
        Get SDK metrics (requires resilience=True).

        Returns:
            Metrics summary including success rate, latencies, errors.
            None if resilience is not enabled.
        """
        if self._resilience:
            return self._resilience.get_metrics()
        return None

    def get_health(self) -> dict[str, Any] | None:
        """
        Get SDK health status (requires resilience=True).

        Returns:
            Health status including circuit breaker state, rate limiter status.
            None if resilience is not enabled.
        """
        if self._resilience:
            return self._resilience.get_health()
        return None

    # =========================================================================
    # Health Check
    # =========================================================================

    async def ping(self) -> dict[str, Any]:
        """
        Ping the Drip API to check connectivity and measure latency.

        Returns:
            Dict with ok (bool), status (str), latency_ms (int), and timestamp.

        Example:
            >>> health = await client.ping()
            >>> if health["ok"]:
            ...     print(f"API healthy, latency: {health['latency_ms']}ms")
        """
        import time

        # Construct health endpoint URL (without /v1)
        health_url = self._base_url
        if health_url.endswith("/v1"):
            health_url = health_url[:-3]
        elif health_url.endswith("/v1/"):
            health_url = health_url[:-4]
        health_url = health_url.rstrip("/") + "/health"

        start = time.time()
        try:
            response = await self._client.get(health_url)
            latency_ms = int((time.time() - start) * 1000)

            try:
                data = response.json()
                status = data.get("status", "unknown")
                timestamp = data.get("timestamp", int(time.time()))
            except Exception:
                status = "healthy" if response.is_success else f"error:{response.status_code}"
                timestamp = int(time.time())

            return {
                "ok": response.is_success and status == "healthy",
                "status": status,
                "latency_ms": latency_ms,
                "timestamp": timestamp,
            }
        except httpx.RequestError as e:
            raise DripNetworkError(f"Ping failed: {e}") from e

    # =========================================================================
    # HTTP Request Helpers
    # =========================================================================

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async HTTP request."""
        if self._resilience:
            return await self._resilience.execute_async(
                lambda: self._raw_request(method, path, json, params),
                method=method,
                endpoint=path,
            )
        return await self._raw_request(method, path, json, params)

    async def _raw_request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the actual async HTTP request (internal)."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "drip request: %s %s body=%s params=%s",
                method,
                path,
                _json_mod.dumps(json, default=str) if json else None,
                _json_mod.dumps(params, default=str) if params else None,
            )
        try:
            response = await self._client.request(
                method=method,
                url=path,
                json=json,
                params=params,
            )
        except httpx.TimeoutException as e:
            raise DripNetworkError(f"Request timed out: {path}", original_error=e) from e
        except httpx.RequestError as e:
            raise DripNetworkError(f"Network error: {e}", original_error=e) from e

        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {"error": response.text or "Unknown error"}

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "drip response: %s %s status=%d body=%s",
                    method,
                    path,
                    response.status_code,
                    _json_mod.dumps(body, default=str),
                )

            error = create_api_error_from_response(response.status_code, body)
            # Add status_code for resilience retry logic
            error.status_code = response.status_code  # type: ignore[attr-defined]
            raise error

        if response.status_code == 204:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("drip response: %s %s status=204 body={}", method, path)
            return {}

        try:
            result: dict[str, Any] = response.json()
        except Exception:
            result = {}

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "drip response: %s %s status=%d body=%s",
                method,
                path,
                response.status_code,
                _json_mod.dumps(result, default=str),
            )

        return result

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async GET request."""
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async POST request."""
        return await self._request("POST", path, json=json)

    async def _put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async PUT request."""
        return await self._request("PUT", path, json=json)

    async def _patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async PATCH request."""
        return await self._request("PATCH", path, json=json)

    async def _delete(self, path: str) -> dict[str, Any]:
        """Make an async DELETE request."""
        return await self._request("DELETE", path)

    # =========================================================================
    # Customer Management
    # =========================================================================

    async def create_customer(
        self,
        onchain_address: str | None = None,
        external_customer_id: str | None = None,
        is_internal: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        """
        Create a new customer.

        At least one of ``onchain_address`` or ``external_customer_id`` is required.
        """
        body: dict[str, Any] = {}

        if onchain_address:
            body["onchainAddress"] = onchain_address
        if external_customer_id:
            body["externalCustomerId"] = external_customer_id
        if is_internal is not None:
            body["isInternal"] = is_internal
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/customers", json=body)
        return Customer.model_validate(response)

    async def get_customer(self, customer_id: str) -> Customer:
        """Get a customer by ID."""
        response = await self._get(f"/customers/{customer_id}")
        return Customer.model_validate(response)

    async def list_customers(
        self,
        status: CustomerStatus | None = None,
        limit: int = 100,
    ) -> ListCustomersResponse:
        """List customers with optional filtering."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status.value

        response = await self._get("/customers", params=params)
        return ListCustomersResponse.model_validate(response)

    async def get_balance(self, customer_id: str) -> BalanceResult:
        """Get a customer's current balance."""
        response = await self._get(f"/customers/{customer_id}/balance")
        return BalanceResult.model_validate(response)

    # =========================================================================
    # Charging & Usage
    # =========================================================================

    async def charge(
        self,
        customer_id: str,
        meter: str,
        quantity: float,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChargeResult:
        """Create a charge for usage."""
        body: dict[str, Any] = {
            "customerId": customer_id,
            "usageType": meter,
            "quantity": quantity,
        }

        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "chg", customer_id, meter, quantity
        )
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/usage", json=body)
        return ChargeResult.model_validate(response)

    async def get_charge(self, charge_id: str) -> Charge:
        """Get detailed charge information."""
        response = await self._get(f"/charges/{charge_id}")
        return Charge.model_validate(response)

    async def list_charges(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> ListChargesResponse:
        """List charges with optional filtering."""
        params: dict[str, Any] = {"limit": limit}
        if customer_id:
            params["customerId"] = customer_id
        if status:
            params["status"] = status

        response = await self._get("/charges", params=params)
        return ListChargesResponse.model_validate(response)

    async def get_charge_status(self, charge_id: str) -> ChargeStatusResult:
        """Quick status check for a charge."""
        response = await self._get(f"/charges/{charge_id}/status")
        return ChargeStatusResult.model_validate(response)

    async def track_usage(
        self,
        customer_id: str,
        meter: str,
        quantity: float,
        idempotency_key: str | None = None,
        units: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrackUsageResult:
        """
        Record usage for internal visibility WITHOUT billing.

        Use this for:
        - Tracking internal team usage without charging
        - Pilot programs where you want visibility before billing
        - Pre-billing tracking before customer wallet setup

        For billing, use `charge()` instead.
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "usageType": meter,
            "quantity": quantity,
        }

        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "track", customer_id, meter, quantity
        )
        if units:
            body["units"] = units
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/usage/internal", json=body)
        return TrackUsageResult.model_validate(response)

    async def wrap_api_call(
        self,
        customer_id: str,
        meter: str,
        call: Callable[[], Any],
        extract_usage: Callable[[Any], float],
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        retry_options: RetryOptions | None = None,
    ) -> WrapApiCallResult:
        """
        Wraps an external async API call with guaranteed usage recording.

        This solves the crash-before-record problem:

        DANGEROUS - usage lost if crash between lines 1 and 2:
        >>> response = await openai.chat.completions.create(...)  # line 1
        >>> await client.charge(customer_id, "tokens", response.usage.total_tokens)  # line 2

        SAFE - wrap_api_call guarantees recording with retry:
        >>> result = await client.wrap_api_call(
        ...     customer_id="cust_123",
        ...     meter="tokens",
        ...     call=lambda: openai.chat.completions.create(...),
        ...     extract_usage=lambda r: r.usage.total_tokens,
        ... )

        How it works:
        1. Generates idempotency key BEFORE the API call
        2. Makes the external API call (once, no retry)
        3. Records usage in Drip with retry + idempotency
        4. If recording fails transiently, retries are safe (no double-charge)

        Args:
            customer_id: The Drip customer ID to charge.
            meter: The usage meter/type to record against.
            call: The async function that makes the external API call.
            extract_usage: Function to extract usage quantity from the API result.
            idempotency_key: Custom idempotency key prefix (auto-generated if not provided).
            metadata: Optional metadata to attach to the charge.
            retry_options: Custom retry options for the charge call.

        Returns:
            WrapApiCallResult containing the API result, charge result, and idempotency key.

        Raises:
            DripAPIError: If the Drip charge fails after retries.
            Exception: If the external API call fails (no retry).

        Example:
            >>> async with AsyncDrip(api_key="...") as client:
            ...     result = await client.wrap_api_call(
            ...         customer_id="cust_abc123",
            ...         meter="tokens",
            ...         call=lambda: openai.chat.completions.create(
            ...             model="gpt-4",
            ...             messages=[{"role": "user", "content": "Hello!"}],
            ...         ),
            ...         extract_usage=lambda r: r.usage.total_tokens if r.usage else 0,
            ...     )
            ...     print(result.result.choices[0].message.content)
            ...     print(f"Charged: {result.charge.charge.amount_usdc} USDC")
        """
        # Generate idempotency key BEFORE the call
        key = idempotency_key or f"wrap_{int(time.time() * 1000)}_{random.randbytes(8).hex()[:9]}"

        # Step 1: Make the external API call (no retry - we don't control this)
        api_result = call()
        # Handle both sync and async calls
        if hasattr(api_result, "__await__"):
            result = await api_result
        else:
            result = api_result

        # Step 2: Extract usage from the result
        quantity = extract_usage(result)

        # Step 3: Record usage in Drip with retry (idempotency makes this safe)
        charge = await _retry_with_backoff_async(
            lambda: self.charge(
                customer_id=customer_id,
                meter=meter,
                quantity=quantity,
                idempotency_key=key,
                metadata=metadata,
            ),
            retry_options,
        )

        return WrapApiCallResult(
            result=result,
            charge=charge,
            idempotency_key=key,
        )

    # =========================================================================
    # Cost Estimation
    # =========================================================================

    async def estimate_from_usage(
        self,
        period_start: datetime | str,
        period_end: datetime | str,
        customer_id: str | None = None,
        default_unit_price: str | None = None,
        include_charged_events: bool | None = None,
        usage_types: list[str] | None = None,
        custom_pricing: dict[str, str] | None = None,
    ) -> CostEstimateResponse:
        """
        Estimates costs from historical usage events.

        Use this to preview what existing usage would cost before creating charges,
        or to run "what-if" scenarios with custom pricing.

        Args:
            period_start: Start of the period to estimate (datetime or ISO string).
            period_end: End of the period to estimate (datetime or ISO string).
            customer_id: Filter to a specific customer (optional).
            default_unit_price: Default price for usage types without pricing plans.
            include_charged_events: Include events that already have charges (default: True).
            usage_types: Filter to specific usage types.
            custom_pricing: Custom pricing overrides (takes precedence over DB pricing).

        Returns:
            CostEstimateResponse with line item breakdown.

        Example:
            >>> async with AsyncDrip(api_key="...") as client:
            ...     estimate = await client.estimate_from_usage(
            ...         period_start=datetime(2024, 1, 1),
            ...         period_end=datetime(2024, 1, 31),
            ...     )
            ...     print(f"Estimated total: ${estimate.estimated_total_usdc}")
        """
        # Convert datetime to ISO string if needed
        start_str = period_start.isoformat() if isinstance(period_start, datetime) else period_start
        end_str = period_end.isoformat() if isinstance(period_end, datetime) else period_end

        body: dict[str, Any] = {
            "periodStart": start_str,
            "periodEnd": end_str,
        }

        if customer_id is not None:
            body["customerId"] = customer_id
        if default_unit_price is not None:
            body["defaultUnitPrice"] = default_unit_price
        if include_charged_events is not None:
            body["includeChargedEvents"] = include_charged_events
        if usage_types is not None:
            body["usageTypes"] = usage_types
        if custom_pricing is not None:
            body["customPricing"] = custom_pricing

        response = await self._post("/dashboard/cost-estimate/from-usage", json=body)
        return CostEstimateResponse.model_validate(response)

    async def estimate_from_hypothetical(
        self,
        items: list[HypotheticalUsageItem] | list[dict[str, Any]],
        default_unit_price: str | None = None,
        custom_pricing: dict[str, str] | None = None,
    ) -> CostEstimateResponse:
        """
        Estimates costs from hypothetical usage.

        Use this for "what-if" scenarios, budget planning, or to preview
        costs before usage occurs.

        Args:
            items: List of usage items to estimate. Each item should have:
                - usage_type (or usageType): The usage type (e.g., "api_call", "token")
                - quantity: The quantity of usage
                - unit_price_override (optional): Override unit price for this item
            default_unit_price: Default price for usage types without pricing plans.
            custom_pricing: Custom pricing overrides (takes precedence over DB pricing).

        Returns:
            CostEstimateResponse with line item breakdown.

        Example:
            >>> async with AsyncDrip(api_key="...") as client:
            ...     estimate = await client.estimate_from_hypothetical(
            ...         items=[
            ...             HypotheticalUsageItem(usage_type="api_call", quantity=10000),
            ...             HypotheticalUsageItem(usage_type="token", quantity=1000000),
            ...         ],
            ...     )
            ...     print(f"Estimated total: ${estimate.estimated_total_usdc}")
        """
        # Convert items to dicts if they're Pydantic models
        items_data: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, HypotheticalUsageItem):
                items_data.append(item.model_dump(by_alias=True, exclude_none=True))
            else:
                items_data.append(item)

        body: dict[str, Any] = {"items": items_data}

        if default_unit_price is not None:
            body["defaultUnitPrice"] = default_unit_price
        if custom_pricing is not None:
            body["customPricing"] = custom_pricing

        response = await self._post("/dashboard/cost-estimate/hypothetical", json=body)
        return CostEstimateResponse.model_validate(response)

    # =========================================================================
    # Checkout
    # =========================================================================

    async def checkout(
        self,
        amount: int,
        return_url: str,
        customer_id: str | None = None,
        external_customer_id: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutResult:
        """Create a checkout session."""
        body: dict[str, Any] = {
            "amount": amount,
            "returnUrl": return_url,
        }

        if customer_id:
            body["customerId"] = customer_id
        if external_customer_id:
            body["externalCustomerId"] = external_customer_id
        if cancel_url:
            body["cancelUrl"] = cancel_url
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/checkout", json=body)
        return CheckoutResult.model_validate(response)

    # =========================================================================
    # Webhooks
    # =========================================================================

    async def create_webhook(
        self,
        url: str,
        events: list[str],
        description: str | None = None,
    ) -> CreateWebhookResponse:
        """Create a webhook endpoint."""
        body: dict[str, Any] = {
            "url": url,
            "events": events,
        }

        if description:
            body["description"] = description

        response = await self._post("/webhooks", json=body)
        return CreateWebhookResponse.model_validate(response)

    async def list_webhooks(self) -> ListWebhooksResponse:
        """List all webhooks."""
        response = await self._get("/webhooks")
        return ListWebhooksResponse.model_validate(response)

    async def get_webhook(self, webhook_id: str) -> Webhook:
        """Get a specific webhook."""
        response = await self._get(f"/webhooks/{webhook_id}")
        return Webhook.model_validate(response)

    async def delete_webhook(self, webhook_id: str) -> DeleteWebhookResponse:
        """Delete a webhook."""
        response = await self._delete(f"/webhooks/{webhook_id}")
        return DeleteWebhookResponse.model_validate(response)

    async def test_webhook(self, webhook_id: str) -> TestWebhookResponse:
        """Send a test event to a webhook."""
        response = await self._post(f"/webhooks/{webhook_id}/test")
        return TestWebhookResponse.model_validate(response)

    async def rotate_webhook_secret(
        self, webhook_id: str
    ) -> RotateWebhookSecretResponse:
        """Generate a new webhook secret."""
        response = await self._post(f"/webhooks/{webhook_id}/rotate-secret")
        return RotateWebhookSecretResponse.model_validate(response)

    # =========================================================================
    # Workflows
    # =========================================================================

    async def create_workflow(
        self,
        name: str,
        slug: str,
        product_surface: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        """Create a workflow definition."""
        body: dict[str, Any] = {
            "name": name,
            "slug": slug,
        }

        if product_surface:
            body["productSurface"] = product_surface
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/workflows", json=body)
        return Workflow.model_validate(response)

    async def list_workflows(self) -> ListWorkflowsResponse:
        """List all workflows."""
        response = await self._get("/workflows")
        return ListWorkflowsResponse.model_validate(response)

    # =========================================================================
    # Agent Runs
    # =========================================================================

    async def start_run(
        self,
        customer_id: str,
        workflow_id: str,
        external_run_id: str | None = None,
        correlation_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunResult:
        """Start a new agent run."""
        body: dict[str, Any] = {
            "customerId": customer_id,
            "workflowId": workflow_id,
        }

        if external_run_id:
            body["externalRunId"] = external_run_id
        if correlation_id:
            body["correlationId"] = correlation_id
        if parent_run_id:
            body["parentRunId"] = parent_run_id
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/runs", json=body)
        return RunResult.model_validate(response)

    async def end_run(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EndRunResult:
        """End an agent run."""
        body: dict[str, Any] = {"status": status}

        if error_message:
            body["errorMessage"] = error_message
        if error_code:
            body["errorCode"] = error_code
        if metadata:
            body["metadata"] = metadata

        response = await self._patch(f"/runs/{run_id}", json=body)
        return EndRunResult.model_validate(response)

    async def emit_event(
        self,
        run_id: str,
        event_type: str,
        quantity: float | None = None,
        units: str | None = None,
        description: str | None = None,
        cost_units: float | None = None,
        cost_currency: str | None = None,
        correlation_id: str | None = None,
        parent_event_id: str | None = None,
        span_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EventResult:
        """Emit an event within a run."""
        body: dict[str, Any] = {
            "runId": run_id,
            "eventType": event_type,
        }

        if quantity is not None:
            body["quantity"] = quantity
        if units:
            body["units"] = units
        if description:
            body["description"] = description
        if cost_units is not None:
            body["costUnits"] = cost_units
        if cost_currency:
            body["costCurrency"] = cost_currency
        if correlation_id:
            body["correlationId"] = correlation_id
        if parent_event_id:
            body["parentEventId"] = parent_event_id
        if span_id:
            body["spanId"] = span_id
        body["idempotencyKey"] = idempotency_key or _deterministic_idempotency_key(
            "evt", run_id, event_type, quantity
        )
        if metadata:
            body["metadata"] = metadata

        response = await self._post("/run-events", json=body)
        return EventResult.model_validate(response)

    async def emit_events_batch(
        self,
        events: list[dict[str, Any]],
    ) -> EmitEventsBatchResult:
        """Emit multiple events in one request."""
        response = await self._post("/run-events/batch", json={"events": events})
        return EmitEventsBatchResult.model_validate(response)

    async def get_run_timeline(self, run_id: str) -> RunTimeline:
        """Get the full timeline for a run."""
        data = await self._get(f"/runs/{run_id}/timeline")

        run = TimelineRunInfo(
            id=data.get("runId", run_id),
            customerId=data.get("customerId", ""),
            customerName=data.get("customerName"),
            workflowId=data.get("workflowId", ""),
            workflowName=data.get("workflowName", ""),
            status=data.get("status", "RUNNING"),
            startedAt=data.get("startedAt"),
            endedAt=data.get("endedAt"),
            durationMs=data.get("durationMs"),
            errorMessage=data.get("errorMessage"),
            errorCode=data.get("errorCode"),
            correlationId=data.get("correlationId"),
            metadata=data.get("metadata"),
        )

        events_data = data.get("events", [])
        timeline = []
        for e in events_data:
            meta = e.get("metadata", {}) if isinstance(e.get("metadata"), dict) else {}
            timeline.append(TimelineEvent(
                id=e["id"],
                eventType=e.get("eventType", e.get("actionName", "")),
                quantity=meta.get("quantity", 0) if isinstance(meta, dict) else 0,
                units=meta.get("units") if isinstance(meta, dict) else None,
                description=e.get("description", e.get("explanation")),
                costUnits=e.get("costUsdc"),
                timestamp=e.get("timestamp", e.get("createdAt", "")),
                correlationId=e.get("correlationId"),
                parentEventId=e.get("parentEventId"),
            ))

        summary_data = data.get("summary", {})
        totals = TimelineTotals(
            eventCount=summary_data.get("totalEvents", len(events_data)) if isinstance(summary_data, dict) else len(events_data),
            totalQuantity=str(summary_data.get("totalQuantity", "0")) if isinstance(summary_data, dict) else "0",
            totalCostUnits=str(summary_data.get("totalCostUnits", "0")) if isinstance(summary_data, dict) else "0",
            totalChargedUsdc=str(summary_data.get("totalChargedUsdc", "0")) if isinstance(summary_data, dict) else "0",
        )

        summary_str = ""
        if isinstance(summary_data, dict):
            summary_str = f"{summary_data.get('totalEvents', len(events_data))} events"
        elif isinstance(summary_data, str):
            summary_str = summary_data

        return RunTimeline(
            run=run,
            timeline=timeline,
            totals=totals,
            summary=summary_str,
        )

    # =========================================================================
    # Simplified API
    # =========================================================================

    async def record_run(
        self,
        customer_id: str,
        workflow: str,
        events: list[dict[str, Any]],
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
        external_run_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecordRunResult:
        """One-call simplified API for recording a complete agent run."""
        # Normalize event keys: accept both snake_case and camelCase
        normalized_events: list[dict[str, Any]] = []
        for event in events:
            evt: dict[str, Any] = {
                "eventType": event.get("event_type", event.get("eventType", "")),
            }
            if "quantity" in event:
                evt["quantity"] = event["quantity"]
            for key in ("units", "description", "metadata"):
                if event.get(key) is not None:
                    evt[key] = event[key]
            cost = event.get("cost_units", event.get("costUnits"))
            if cost is not None:
                evt["costUnits"] = cost
            normalized_events.append(evt)

        body: dict[str, Any] = {
            "customerId": customer_id,
            "workflow": workflow,
            "events": normalized_events,
            "status": status,
        }
        if error_message:
            body["errorMessage"] = error_message
        if error_code:
            body["errorCode"] = error_code
        if external_run_id:
            body["externalRunId"] = external_run_id
        if correlation_id:
            body["correlationId"] = correlation_id
        if metadata:
            body["metadata"] = metadata

        # Try single-call endpoint; fall back to 4-step if server returns 404
        try:
            data = await self._post("/runs/record", json=body)
            return RecordRunResult.model_validate(data)
        except DripError as e:
            if e.status_code != 404:
                raise

        return await self._record_run_fallback(
            customer_id, workflow, normalized_events, status,
            error_message, error_code, external_run_id, correlation_id, metadata,
        )

    async def _record_run_fallback(
        self,
        customer_id: str,
        workflow: str,
        events: list[dict[str, Any]],
        status: str,
        error_message: str | None,
        error_code: str | None,
        external_run_id: str | None,
        correlation_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> RecordRunResult:
        """4-step orchestration fallback for servers without POST /runs/record."""
        import time as _time

        start = _time.monotonic()

        # Step 1: Resolve workflow
        workflows_resp = await self.list_workflows()
        match = next(
            (w for w in workflows_resp.data if w.slug == workflow or w.id == workflow),
            None,
        )
        if match:
            workflow_id = match.id
            workflow_name = match.name
        else:
            pretty = workflow.replace("_", " ").replace("-", " ").title()
            created = await self._post("/workflows", json={
                "name": pretty, "slug": workflow, "productSurface": "CUSTOM",
            })
            workflow_id = created["id"]
            workflow_name = created["name"]

        # Step 2: Start run
        run = await self.start_run(
            customer_id=customer_id,
            workflow_id=workflow_id,
            external_run_id=external_run_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )

        # Step 3: Emit events
        events_created = 0
        events_duplicates = 0
        if events:
            batch: list[dict[str, Any]] = []
            for i, evt in enumerate(events):
                entry: dict[str, Any] = {
                    "runId": run.id,
                    "eventType": evt["eventType"],
                    "quantity": evt.get("quantity", 1),
                }
                for key in ("units", "description", "costUnits", "metadata"):
                    if key in evt:
                        entry[key] = evt[key]
                if external_run_id:
                    entry["idempotencyKey"] = f"{external_run_id}:{evt['eventType']}:{i}"
                batch.append(entry)
            result = await self.emit_events_batch(batch)
            events_created = result.created
            events_duplicates = result.duplicates

        # Step 4: End run
        end_result = await self.end_run(
            run_id=run.id,
            status=status,
            error_message=error_message,
            error_code=error_code,
        )

        elapsed_ms = int((_time.monotonic() - start) * 1000)
        dur = end_result.duration_ms if end_result.duration_ms is not None else elapsed_ms
        icon = "\u2713" if status == "COMPLETED" else "\u2717" if status == "FAILED" else "\u25CB"

        return RecordRunResult.model_validate({
            "run": {
                "id": run.id,
                "workflowId": workflow_id,
                "workflowName": workflow_name,
                "status": end_result.status.value,
                "durationMs": dur,
            },
            "events": {"created": events_created, "duplicates": events_duplicates},
            "totalCostUnits": end_result.total_cost_units,
            "summary": f"{icon} {workflow_name}: {events_created} events recorded ({dur}ms)",
        })

    # =========================================================================
    # Meters
    # =========================================================================

    async def list_meters(self) -> ListMetersResponse:
        """List available usage meters."""
        response = await self._get("/pricing-plans")
        plans = response.get("data", [])
        return ListMetersResponse(
            data=[
                Meter(
                    id=p["id"],
                    name=p["name"],
                    meter=p["unitType"],
                    unitPriceUsd=p["unitPriceUsd"],
                    isActive=p["isActive"],
                )
                for p in plans
            ],
            count=response.get("count", len(plans)),
        )

    # =========================================================================
    # Static Utility Methods
    # =========================================================================

    @staticmethod
    def generate_idempotency_key(
        customer_id: str,
        step_name: str,
        run_id: str | None = None,
        sequence: int | None = None,
    ) -> str:
        """Generate a deterministic idempotency key."""
        return generate_idempotency_key(customer_id, step_name, run_id, sequence)

    @staticmethod
    def verify_webhook_signature(
        payload: str,
        signature: str,
        secret: str,
    ) -> bool:
        """Verify a webhook signature."""
        return verify_webhook_signature(payload, signature, secret)

    # =========================================================================
    # StreamMeter Factory
    # =========================================================================

    def create_stream_meter(
        self,
        customer_id: str,
        meter: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush_threshold: float | None = None,
        on_add: Any = None,
        on_flush: Any = None,
    ) -> StreamMeter:
        """
        Create a StreamMeter for accumulating usage and charging once (async).

        Perfect for LLM token streaming where you want to:
        - Accumulate tokens locally (no API call per token)
        - Charge once at the end of the stream
        - Handle partial failures (charge for what was delivered)

        Args:
            customer_id: The Drip customer ID to charge.
            meter: The usage meter/type to record against.
            idempotency_key: Optional base key for idempotent charges.
            metadata: Optional metadata to attach to the charge.
            flush_threshold: Optional auto-flush when quantity exceeds this.
            on_add: Optional callback(quantity, total) on each add.
            on_flush: Optional callback(result) after each flush.

        Returns:
            A new StreamMeter instance.

        Example:
            >>> async with AsyncDrip(api_key="...") as client:
            ...     meter = client.create_stream_meter(
            ...         customer_id="cust_abc123",
            ...         meter="tokens",
            ...     )
            ...
            ...     async for chunk in llm_stream:
            ...         await meter.add(chunk.tokens)  # May auto-flush
            ...
            ...     result = await meter.flush_async()
            ...     print(f"Charged {result.charge.amount_usdc}")
        """
        options = StreamMeterOptions(
            customer_id=customer_id,
            meter=meter,
            idempotency_key=idempotency_key,
            metadata=metadata,
            flush_threshold=flush_threshold,
            on_add=on_add,
            on_flush=on_flush,
        )
        return StreamMeter(_charge_fn=self.charge, _options=options)
