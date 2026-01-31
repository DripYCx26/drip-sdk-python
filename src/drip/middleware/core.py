"""
Drip middleware core logic.

This module contains framework-agnostic middleware logic for processing
requests, resolving customers, handling payments, and creating charges.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, TypeVar

from ..client import AsyncDrip, Drip
from ..errors import (
    DripMiddlewareError,
    DripMiddlewareErrorCode,
    DripPaymentRequiredError,
)
from ..models import ChargeResult, X402PaymentProof, X402PaymentRequest
from ..utils import current_timestamp, generate_idempotency_key, generate_nonce
from .types import (
    DripContext,
    DripMiddlewareConfig,
    PaymentRequestHeaders,
    ProcessRequestResult,
)

T = TypeVar("T")


# =============================================================================
# Header Utilities
# =============================================================================


def get_header(headers: dict[str, Any], name: str) -> str | None:
    """
    Get a header value case-insensitively.

    Args:
        headers: Dictionary of headers.
        name: Header name to look for.

    Returns:
        Header value or None if not found.
    """
    name_lower = name.lower()

    for key, value in headers.items():
        if key.lower() == name_lower:
            if isinstance(value, list):
                return value[0] if value else None
            return str(value) if value is not None else None

    return None


def has_payment_proof_headers(headers: dict[str, Any]) -> bool:
    """
    Check if request has x402 payment proof headers.

    Args:
        headers: Request headers.

    Returns:
        True if payment proof headers are present.
    """
    signature = get_header(headers, "X-Payment-Signature")
    return signature is not None and len(signature) > 0


# =============================================================================
# Payment Proof Parsing
# =============================================================================


def is_valid_hex(value: str) -> bool:
    """Check if a string is valid hex."""
    if not value:
        return False
    clean = value[2:] if value.lower().startswith("0x") else value
    return bool(re.match(r"^[0-9a-fA-F]+$", clean))


def parse_payment_proof(headers: dict[str, Any]) -> X402PaymentProof | None:
    """
    Parse x402 payment proof from request headers.

    Args:
        headers: Request headers.

    Returns:
        X402PaymentProof if valid headers present, None otherwise.
    """
    signature = get_header(headers, "X-Payment-Signature")
    session_key_id = get_header(headers, "X-Payment-Session-Key")
    smart_account = get_header(headers, "X-Payment-Smart-Account")
    timestamp_str = get_header(headers, "X-Payment-Timestamp")
    amount = get_header(headers, "X-Payment-Amount")
    recipient = get_header(headers, "X-Payment-Recipient")
    usage_id = get_header(headers, "X-Payment-Usage-Id")
    nonce = get_header(headers, "X-Payment-Nonce")

    # Validate required fields
    if not all([signature, session_key_id, smart_account, timestamp_str, amount, recipient, usage_id, nonce]):
        return None

    # Validate hex values
    if not is_valid_hex(signature):  # type: ignore[arg-type]
        return None
    if not is_valid_hex(smart_account):  # type: ignore[arg-type]
        return None

    # Parse timestamp
    try:
        timestamp = int(timestamp_str)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None

    # Check timestamp freshness (5 minutes)
    now = current_timestamp()
    if abs(now - timestamp) > 300:
        return None

    return X402PaymentProof.model_validate({
        "signature": signature,
        "sessionKeyId": session_key_id,
        "smartAccount": smart_account,
        "timestamp": timestamp,
        "amount": amount,
        "recipient": recipient,
        "usageId": usage_id,
        "nonce": nonce,
    })


# =============================================================================
# Payment Request Generation
# =============================================================================


def generate_payment_request(
    amount: str,
    recipient: str,
    usage_id: str,
    description: str,
    expires_in_seconds: int = 300,
) -> tuple[PaymentRequestHeaders, X402PaymentRequest]:
    """
    Generate a 402 payment request.

    Args:
        amount: Amount in smallest unit.
        recipient: Payment recipient address.
        usage_id: Usage ID for tracking.
        description: Human-readable description.
        expires_in_seconds: Expiration time (default 5 minutes).

    Returns:
        Tuple of (headers, payment_request).
    """
    now = current_timestamp()
    nonce = generate_nonce(16)
    expires_at = now + expires_in_seconds

    headers = PaymentRequestHeaders(
        x_payment_required="true",
        x_payment_amount=amount,
        x_payment_recipient=recipient,
        x_payment_usage_id=usage_id,
        x_payment_description=description,
        x_payment_expires=str(expires_at),
        x_payment_nonce=nonce,
        x_payment_timestamp=str(now),
    )

    payment_request = X402PaymentRequest.model_validate({
        "amount": amount,
        "recipient": recipient,
        "usageId": usage_id,
        "description": description,
        "expiresAt": expires_at,
        "nonce": nonce,
        "timestamp": now,
    })

    return headers, payment_request


# =============================================================================
# Customer Resolution
# =============================================================================


def resolve_customer_id_sync(
    request: Any,
    config: DripMiddlewareConfig,
) -> str:
    """
    Resolve customer ID from request (sync version).

    Args:
        request: The HTTP request.
        config: Middleware configuration.

    Returns:
        Customer ID.

    Raises:
        DripMiddlewareError: If customer cannot be resolved.
    """
    resolver = config.customer_resolver

    if resolver == "header":
        # Get from X-Drip-Customer-Id header
        headers = getattr(request, "headers", {})
        if isinstance(headers, dict):
            customer_id = get_header(headers, "X-Drip-Customer-Id")
        else:
            # Handle Headers-like objects
            customer_id = headers.get("X-Drip-Customer-Id") or headers.get("x-drip-customer-id")

        if not customer_id:
            raise DripMiddlewareError(
                "Customer ID not found in X-Drip-Customer-Id header",
                DripMiddlewareErrorCode.CUSTOMER_NOT_FOUND,
                status_code=400,
            )
        return customer_id

    elif resolver == "query":
        # Get from query parameter
        query_params: dict[str, Any] = {}

        # Try different ways to access query params
        if hasattr(request, "query_params"):
            query_params = dict(request.query_params)
        elif hasattr(request, "args"):
            query_params = dict(request.args)
        elif hasattr(request, "query"):
            query_params = dict(request.query)

        customer_id = query_params.get("customer_id") or query_params.get("customerId")

        if not customer_id:
            raise DripMiddlewareError(
                "Customer ID not found in customer_id query parameter",
                DripMiddlewareErrorCode.CUSTOMER_NOT_FOUND,
                status_code=400,
            )
        return str(customer_id)

    elif callable(resolver):
        try:
            result = resolver(request)
            # Handle coroutines in sync context
            if asyncio.iscoroutine(result):
                raise DripMiddlewareError(
                    "Async customer resolver used in sync context",
                    DripMiddlewareErrorCode.CONFIGURATION_ERROR,
                    status_code=500,
                )
            return str(result)
        except DripMiddlewareError:
            raise
        except Exception as e:
            raise DripMiddlewareError(
                f"Customer resolution failed: {e}",
                DripMiddlewareErrorCode.CUSTOMER_RESOLUTION_FAILED,
                status_code=500,
            ) from e

    else:
        raise DripMiddlewareError(
            f"Invalid customer resolver: {resolver}",
            DripMiddlewareErrorCode.CONFIGURATION_ERROR,
            status_code=500,
        )


async def resolve_customer_id_async(
    request: Any,
    config: DripMiddlewareConfig,
) -> str:
    """
    Resolve customer ID from request (async version).

    Args:
        request: The HTTP request.
        config: Middleware configuration.

    Returns:
        Customer ID.

    Raises:
        DripMiddlewareError: If customer cannot be resolved.
    """
    resolver = config.customer_resolver

    if resolver == "header":
        headers = getattr(request, "headers", {})
        if isinstance(headers, dict):
            customer_id = get_header(headers, "X-Drip-Customer-Id")
        else:
            customer_id = headers.get("X-Drip-Customer-Id") or headers.get("x-drip-customer-id")

        if not customer_id:
            raise DripMiddlewareError(
                "Customer ID not found in X-Drip-Customer-Id header",
                DripMiddlewareErrorCode.CUSTOMER_NOT_FOUND,
                status_code=400,
            )
        return customer_id

    elif resolver == "query":
        query_params: dict[str, Any] = {}

        if hasattr(request, "query_params"):
            query_params = dict(request.query_params)
        elif hasattr(request, "args"):
            query_params = dict(request.args)
        elif hasattr(request, "query"):
            query_params = dict(request.query)

        customer_id = query_params.get("customer_id") or query_params.get("customerId")

        if not customer_id:
            raise DripMiddlewareError(
                "Customer ID not found in customer_id query parameter",
                DripMiddlewareErrorCode.CUSTOMER_NOT_FOUND,
                status_code=400,
            )
        return str(customer_id)

    elif callable(resolver):
        try:
            result = resolver(request)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except DripMiddlewareError:
            raise
        except Exception as e:
            raise DripMiddlewareError(
                f"Customer resolution failed: {e}",
                DripMiddlewareErrorCode.CUSTOMER_RESOLUTION_FAILED,
                status_code=500,
            ) from e

    else:
        raise DripMiddlewareError(
            f"Invalid customer resolver: {resolver}",
            DripMiddlewareErrorCode.CONFIGURATION_ERROR,
            status_code=500,
        )


# =============================================================================
# Quantity Resolution
# =============================================================================


def resolve_quantity_sync(request: Any, config: DripMiddlewareConfig) -> float:
    """Resolve quantity (sync version)."""
    quantity = config.quantity

    if callable(quantity):
        result = quantity(request)
        if asyncio.iscoroutine(result):
            raise DripMiddlewareError(
                "Async quantity resolver used in sync context",
                DripMiddlewareErrorCode.CONFIGURATION_ERROR,
                status_code=500,
            )
        # Result is guaranteed to be float at this point
        return float(result)  # type: ignore[arg-type]

    return float(quantity)


async def resolve_quantity_async(request: Any, config: DripMiddlewareConfig) -> float:
    """Resolve quantity (async version)."""
    quantity = config.quantity

    if callable(quantity):
        result = quantity(request)
        if asyncio.iscoroutine(result):
            result = await result
        return float(result)  # type: ignore[arg-type]

    return float(quantity)


# =============================================================================
# Idempotency Key Generation
# =============================================================================


def generate_request_idempotency_key_sync(
    request: Any,
    customer_id: str,
    config: DripMiddlewareConfig,
) -> str:
    """Generate idempotency key for request (sync version)."""
    if config.idempotency_key:
        result = config.idempotency_key(request, customer_id)
        if asyncio.iscoroutine(result):
            raise DripMiddlewareError(
                "Async idempotency key generator used in sync context",
                DripMiddlewareErrorCode.CONFIGURATION_ERROR,
                status_code=500,
            )
        return str(result)

    # Default: hash of customer_id, meter, method, path
    method = getattr(request, "method", "GET")
    url = getattr(request, "url", "")
    path = str(url).split("?")[0] if url else ""

    return generate_idempotency_key(
        customer_id=customer_id,
        step_name=f"{method}:{path}:{config.meter}",
    )


async def generate_request_idempotency_key_async(
    request: Any,
    customer_id: str,
    config: DripMiddlewareConfig,
) -> str:
    """Generate idempotency key for request (async version)."""
    if config.idempotency_key:
        result = config.idempotency_key(request, customer_id)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)

    method = getattr(request, "method", "GET")
    url = getattr(request, "url", "")
    path = str(url).split("?")[0] if url else ""

    return generate_idempotency_key(
        customer_id=customer_id,
        step_name=f"{method}:{path}:{config.meter}",
    )


# =============================================================================
# Metadata Resolution
# =============================================================================


def resolve_metadata_sync(
    request: Any,
    config: DripMiddlewareConfig,
) -> dict[str, Any] | None:
    """Resolve metadata (sync version)."""
    metadata = config.metadata

    if metadata is None:
        return None

    if callable(metadata):
        result = metadata(request)
        if asyncio.iscoroutine(result):
            raise DripMiddlewareError(
                "Async metadata resolver used in sync context",
                DripMiddlewareErrorCode.CONFIGURATION_ERROR,
                status_code=500,
            )
        return result

    return metadata


async def resolve_metadata_async(
    request: Any,
    config: DripMiddlewareConfig,
) -> dict[str, Any] | None:
    """Resolve metadata (async version)."""
    metadata = config.metadata

    if metadata is None:
        return None

    if callable(metadata):
        result = metadata(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    return metadata


# =============================================================================
# Client Creation
# =============================================================================


def create_drip_client(config: DripMiddlewareConfig) -> Drip:
    """Create a sync Drip client from config."""
    return Drip(
        api_key=config.api_key or os.environ.get("DRIP_API_KEY"),
        base_url=config.base_url or os.environ.get("DRIP_API_URL"),
    )


def create_async_drip_client(config: DripMiddlewareConfig) -> AsyncDrip:
    """Create an async Drip client from config."""
    return AsyncDrip(
        api_key=config.api_key or os.environ.get("DRIP_API_KEY"),
        base_url=config.base_url or os.environ.get("DRIP_API_URL"),
    )


# =============================================================================
# Request Processing
# =============================================================================


def process_request_sync(
    request: Any,
    config: DripMiddlewareConfig,
) -> ProcessRequestResult:
    """
    Process a request through the middleware (sync version).

    Args:
        request: The HTTP request.
        config: Middleware configuration.

    Returns:
        ProcessRequestResult with success status and context or error.
    """
    # Check for development mode skip
    if config.skip_in_development:
        env = os.environ.get("DRIP_ENV") or os.environ.get("NODE_ENV") or os.environ.get("ENVIRONMENT")
        if env in ("development", "dev", "local"):
            # Return mock successful response
            from ..models import ChargeInfo, ChargeStatus

            mock_charge_info = ChargeInfo.model_validate({
                "id": "dev_mock_charge",
                "amountUsdc": "0",
                "amountToken": "0",
                "txHash": "0x0",
                "status": ChargeStatus.CONFIRMED,
            })
            mock_charge = ChargeResult.model_validate({
                "success": True,
                "usageEventId": "dev_mock_usage",
                "isDuplicate": False,
                "charge": mock_charge_info,
            })
            client = create_drip_client(config)
            return ProcessRequestResult(
                success=True,
                context=DripContext(
                    drip=client,
                    customer_id="dev_mock_customer",
                    charge=mock_charge,
                    is_duplicate=False,
                ),
            )

    try:
        # Resolve customer ID
        customer_id = resolve_customer_id_sync(request, config)

        # Resolve quantity
        quantity = resolve_quantity_sync(request, config)

        # Generate idempotency key
        idempotency_key = generate_request_idempotency_key_sync(request, customer_id, config)

        # Resolve metadata
        metadata = resolve_metadata_sync(request, config)

        # Create client and charge
        client = create_drip_client(config)

        try:
            charge_result = client.charge(
                customer_id=customer_id,
                meter=config.meter,
                quantity=quantity,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        except DripPaymentRequiredError as e:
            # Generate 402 response
            payment_request = e.payment_request or {}
            headers, pr = generate_payment_request(
                amount=payment_request.get("amount", "0"),
                recipient=payment_request.get("recipient", ""),
                usage_id=payment_request.get("usageId", ""),
                description=f"Payment for {config.meter}",
            )
            return ProcessRequestResult(
                success=False,
                payment_required=True,
                payment_request=pr,
                payment_headers=headers,
            )

        # Call success callback if provided
        if config.on_charge:
            config.on_charge(charge_result, request)

        return ProcessRequestResult(
            success=True,
            context=DripContext(
                drip=client,
                customer_id=customer_id,
                charge=charge_result,
                is_duplicate=charge_result.is_duplicate,
            ),
        )

    except DripMiddlewareError as e:
        if config.on_error:
            config.on_error(e, request)
        return ProcessRequestResult(success=False, error=e)

    except Exception as e:
        error = DripMiddlewareError(
            f"Internal error: {e}",
            DripMiddlewareErrorCode.INTERNAL_ERROR,
            status_code=500,
        )
        if config.on_error:
            config.on_error(error, request)
        return ProcessRequestResult(success=False, error=error)


async def process_request_async(
    request: Any,
    config: DripMiddlewareConfig,
) -> ProcessRequestResult:
    """
    Process a request through the middleware (async version).

    Args:
        request: The HTTP request.
        config: Middleware configuration.

    Returns:
        ProcessRequestResult with success status and context or error.
    """
    # Check for development mode skip
    if config.skip_in_development:
        env = os.environ.get("DRIP_ENV") or os.environ.get("NODE_ENV") or os.environ.get("ENVIRONMENT")
        if env in ("development", "dev", "local"):
            from ..models import ChargeInfo, ChargeStatus

            mock_charge_info = ChargeInfo.model_validate({
                "id": "dev_mock_charge",
                "amountUsdc": "0",
                "amountToken": "0",
                "txHash": "0x0",
                "status": ChargeStatus.CONFIRMED,
            })
            mock_charge = ChargeResult.model_validate({
                "success": True,
                "usageEventId": "dev_mock_usage",
                "isDuplicate": False,
                "charge": mock_charge_info,
            })
            client = create_async_drip_client(config)
            return ProcessRequestResult(
                success=True,
                context=DripContext(
                    drip=client,
                    customer_id="dev_mock_customer",
                    charge=mock_charge,
                    is_duplicate=False,
                ),
            )

    try:
        # Resolve customer ID
        customer_id = await resolve_customer_id_async(request, config)

        # Resolve quantity
        quantity = await resolve_quantity_async(request, config)

        # Generate idempotency key
        idempotency_key = await generate_request_idempotency_key_async(request, customer_id, config)

        # Resolve metadata
        metadata = await resolve_metadata_async(request, config)

        # Create client and charge
        client = create_async_drip_client(config)

        try:
            charge_result = await client.charge(
                customer_id=customer_id,
                meter=config.meter,
                quantity=quantity,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        except DripPaymentRequiredError as e:
            payment_request = e.payment_request or {}
            headers, pr = generate_payment_request(
                amount=payment_request.get("amount", "0"),
                recipient=payment_request.get("recipient", ""),
                usage_id=payment_request.get("usageId", ""),
                description=f"Payment for {config.meter}",
            )
            return ProcessRequestResult(
                success=False,
                payment_required=True,
                payment_request=pr,
                payment_headers=headers,
            )

        # Call success callback if provided
        if config.on_charge:
            result = config.on_charge(charge_result, request)
            if asyncio.iscoroutine(result):
                await result

        return ProcessRequestResult(
            success=True,
            context=DripContext(
                drip=client,
                customer_id=customer_id,
                charge=charge_result,
                is_duplicate=charge_result.is_duplicate,
            ),
        )

    except DripMiddlewareError as e:
        if config.on_error:
            result = config.on_error(e, request)
            if asyncio.iscoroutine(result):
                await result
        return ProcessRequestResult(success=False, error=e)

    except Exception as e:
        error = DripMiddlewareError(
            f"Internal error: {e}",
            DripMiddlewareErrorCode.INTERNAL_ERROR,
            status_code=500,
        )
        if config.on_error:
            result = config.on_error(error, request)
            if asyncio.iscoroutine(result):
                await result
        return ProcessRequestResult(success=False, error=error)
