"""Tests for middleware core functionality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from drip.middleware.core import (
    generate_payment_request,
    get_header,
    has_payment_proof_headers,
    is_valid_hex,
    parse_payment_proof,
)
from drip.utils import current_timestamp

# =============================================================================
# Mock Request
# =============================================================================


@dataclass
class MockRequest:
    """Mock HTTP request for testing."""

    method: str = "GET"
    url: str = "/api/test"
    headers: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}
        if self.query_params is None:
            self.query_params = {}


# =============================================================================
# Header Utilities Tests
# =============================================================================


class TestGetHeader:
    def test_get_header_exact_case(self) -> None:
        """Should find header with exact case match."""
        headers = {"Content-Type": "application/json"}
        assert get_header(headers, "Content-Type") == "application/json"

    def test_get_header_case_insensitive(self) -> None:
        """Should find header regardless of case."""
        headers = {"Content-Type": "application/json"}
        assert get_header(headers, "content-type") == "application/json"
        assert get_header(headers, "CONTENT-TYPE") == "application/json"

    def test_get_header_not_found(self) -> None:
        """Should return None for missing header."""
        headers = {"Content-Type": "application/json"}
        assert get_header(headers, "Authorization") is None

    def test_get_header_list_value(self) -> None:
        """Should return first value from list."""
        headers = {"Accept": ["application/json", "text/html"]}
        assert get_header(headers, "Accept") == "application/json"

    def test_get_header_empty_list(self) -> None:
        """Should return None for empty list."""
        headers = {"Accept": []}
        assert get_header(headers, "Accept") is None


class TestHasPaymentProofHeaders:
    def test_has_payment_proof_headers(self) -> None:
        """Should detect payment proof headers."""
        headers = {"X-Payment-Signature": "0xabc123"}
        assert has_payment_proof_headers(headers) is True

    def test_missing_payment_proof_headers(self) -> None:
        """Should return False without payment proof headers."""
        headers = {"Content-Type": "application/json"}
        assert has_payment_proof_headers(headers) is False

    def test_empty_signature(self) -> None:
        """Should return False for empty signature."""
        headers = {"X-Payment-Signature": ""}
        assert has_payment_proof_headers(headers) is False


# =============================================================================
# Payment Proof Parsing Tests
# =============================================================================


class TestParsePaymentProof:
    def test_parse_valid_payment_proof(self) -> None:
        """Should parse valid payment proof headers."""
        now = current_timestamp()
        headers = {
            "X-Payment-Signature": "0xabc123def456",
            "X-Payment-Session-Key": "sk_123",
            "X-Payment-Smart-Account": "0x1234567890abcdef1234567890abcdef12345678",
            "X-Payment-Timestamp": str(now),
            "X-Payment-Amount": "1000000",
            "X-Payment-Recipient": "0xrecipient",
            "X-Payment-Usage-Id": "usage_123",
            "X-Payment-Nonce": "nonce123",
        }

        proof = parse_payment_proof(headers)
        assert proof is not None
        assert proof.signature == "0xabc123def456"
        assert proof.session_key_id == "sk_123"
        assert proof.amount == "1000000"

    def test_parse_missing_signature(self) -> None:
        """Should return None for missing signature."""
        headers = {
            "X-Payment-Session-Key": "sk_123",
            "X-Payment-Smart-Account": "0x123",
        }
        assert parse_payment_proof(headers) is None

    def test_parse_invalid_signature(self) -> None:
        """Should return None for invalid hex signature."""
        now = current_timestamp()
        headers = {
            "X-Payment-Signature": "not-hex-zzz",
            "X-Payment-Session-Key": "sk_123",
            "X-Payment-Smart-Account": "0x1234567890abcdef1234567890abcdef12345678",
            "X-Payment-Timestamp": str(now),
            "X-Payment-Amount": "1000000",
            "X-Payment-Recipient": "0xrecipient",
            "X-Payment-Usage-Id": "usage_123",
            "X-Payment-Nonce": "nonce123",
        }
        assert parse_payment_proof(headers) is None

    def test_parse_expired_timestamp(self) -> None:
        """Should return None for expired timestamp (>5 minutes old)."""
        old_timestamp = current_timestamp() - 400  # 6+ minutes ago
        headers = {
            "X-Payment-Signature": "0xabc123",
            "X-Payment-Session-Key": "sk_123",
            "X-Payment-Smart-Account": "0x1234567890abcdef1234567890abcdef12345678",
            "X-Payment-Timestamp": str(old_timestamp),
            "X-Payment-Amount": "1000000",
            "X-Payment-Recipient": "0xrecipient",
            "X-Payment-Usage-Id": "usage_123",
            "X-Payment-Nonce": "nonce123",
        }
        assert parse_payment_proof(headers) is None

    def test_parse_invalid_timestamp(self) -> None:
        """Should return None for non-numeric timestamp."""
        headers = {
            "X-Payment-Signature": "0xabc123",
            "X-Payment-Session-Key": "sk_123",
            "X-Payment-Smart-Account": "0x1234567890abcdef1234567890abcdef12345678",
            "X-Payment-Timestamp": "invalid",
            "X-Payment-Amount": "1000000",
            "X-Payment-Recipient": "0xrecipient",
            "X-Payment-Usage-Id": "usage_123",
            "X-Payment-Nonce": "nonce123",
        }
        assert parse_payment_proof(headers) is None


# =============================================================================
# Payment Request Generation Tests
# =============================================================================


class TestGeneratePaymentRequest:
    def test_generate_payment_request(self) -> None:
        """Should generate payment request with headers."""
        headers, request = generate_payment_request(
            amount="1000000",
            recipient="0xrecipient",
            usage_id="usage_123",
            description="Test payment",
        )

        assert headers.x_payment_required == "true"
        assert headers.x_payment_amount == "1000000"
        assert headers.x_payment_recipient == "0xrecipient"
        assert headers.x_payment_usage_id == "usage_123"
        assert headers.x_payment_description == "Test payment"

        assert request.amount == "1000000"
        assert request.recipient == "0xrecipient"
        assert request.usage_id == "usage_123"
        assert request.description == "Test payment"
        assert len(request.nonce) > 0

    def test_generate_payment_request_expiration(self) -> None:
        """Should set correct expiration time."""
        now = current_timestamp()
        headers, request = generate_payment_request(
            amount="1000000",
            recipient="0x123",
            usage_id="usage_123",
            description="Test",
            expires_in_seconds=600,
        )

        # Should expire ~10 minutes from now
        assert request.expires_at >= now + 590
        assert request.expires_at <= now + 610

    def test_headers_to_dict(self) -> None:
        """Should convert headers to dictionary."""
        headers, _ = generate_payment_request(
            amount="1000000",
            recipient="0x123",
            usage_id="usage_123",
            description="Test",
        )

        header_dict = headers.to_dict()
        assert "X-Payment-Required" in header_dict
        assert "X-Payment-Amount" in header_dict
        assert header_dict["X-Payment-Required"] == "true"


# =============================================================================
# Hex Validation Tests
# =============================================================================


class TestIsValidHex:
    def test_valid_hex_lowercase(self) -> None:
        """Should accept lowercase hex."""
        assert is_valid_hex("abc123") is True

    def test_valid_hex_uppercase(self) -> None:
        """Should accept uppercase hex."""
        assert is_valid_hex("ABC123") is True

    def test_valid_hex_with_prefix(self) -> None:
        """Should accept hex with 0x prefix."""
        assert is_valid_hex("0xabc123") is True
        assert is_valid_hex("0XABC123") is True

    def test_invalid_hex(self) -> None:
        """Should reject non-hex strings."""
        assert is_valid_hex("xyz") is False
        assert is_valid_hex("0xghi") is False

    def test_empty_string(self) -> None:
        """Should reject empty string."""
        assert is_valid_hex("") is False
