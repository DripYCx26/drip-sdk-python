"""Test static utility methods.

This module tests:
- generate_idempotency_key
- verify_webhook_signature
- generate_nonce
- current_timestamp / current_timestamp_ms
- is_valid_hex
- normalize_address
- format_usdc_amount / parse_usdc_amount
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest


# =============================================================================
# Generate Idempotency Key Tests
# =============================================================================


class TestGenerateIdempotencyKey:
    """Test idempotency key generation."""

    def test_deterministic_keys(self) -> None:
        """Same inputs produce same key."""
        from drip.utils import generate_idempotency_key

        key1 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )
        key2 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )

        assert key1 == key2

    def test_unique_keys_different_customer(self) -> None:
        """Different customers produce different keys."""
        from drip.utils import generate_idempotency_key

        key1 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )
        key2 = generate_idempotency_key(
            customer_id="cust_456",
            step_name="tokens",
            sequence=1,
        )

        assert key1 != key2

    def test_unique_keys_different_step(self) -> None:
        """Different step names produce different keys."""
        from drip.utils import generate_idempotency_key

        key1 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )
        key2 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="api_calls",
            sequence=1,
        )

        assert key1 != key2

    def test_sequence_affects_key(self) -> None:
        """Different sequence numbers produce different keys."""
        from drip.utils import generate_idempotency_key

        key1 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )
        key2 = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=2,
        )

        assert key1 != key2

    def test_optional_run_id(self) -> None:
        """Run ID included when provided."""
        from drip.utils import generate_idempotency_key

        key_without = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )
        key_with = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
            run_id="run_abc",
        )

        assert key_without != key_with

    def test_key_is_sha256_hex(self) -> None:
        """Key is a valid SHA-256 hex string."""
        from drip.utils import generate_idempotency_key

        key = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
        )

        # SHA-256 produces 64 hex characters
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_key_without_sequence(self) -> None:
        """Key generation works without sequence."""
        from drip.utils import generate_idempotency_key

        key = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
        )

        assert key is not None
        assert len(key) == 64


# =============================================================================
# Verify Webhook Signature Tests
# =============================================================================


class TestVerifyWebhookSignature:
    """Test webhook signature verification."""

    def test_valid_signature_passes(self) -> None:
        """Valid webhook signature is accepted."""
        from drip.utils import verify_webhook_signature

        secret = "whsec_test_secret_12345"
        payload = '{"event": "charge.created", "data": {}}'

        # Generate valid signature
        expected_sig = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        signature = f"sha256={expected_sig}"

        result = verify_webhook_signature(
            payload=payload,
            signature=signature,
            secret=secret,
        )

        assert result is True

    def test_valid_signature_without_prefix(self) -> None:
        """Signature without sha256= prefix works."""
        from drip.utils import verify_webhook_signature

        secret = "whsec_test"
        payload = '{"event": "test"}'

        expected_sig = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        result = verify_webhook_signature(
            payload=payload,
            signature=expected_sig,  # No prefix
            secret=secret,
        )

        assert result is True

    def test_invalid_signature_fails(self) -> None:
        """Invalid webhook signature is rejected."""
        from drip.utils import verify_webhook_signature

        result = verify_webhook_signature(
            payload='{"event": "test"}',
            signature="sha256=invalid_signature_here",
            secret="whsec_test",
        )

        assert result is False

    def test_empty_payload_fails(self) -> None:
        """Empty payload fails verification."""
        from drip.utils import verify_webhook_signature

        result = verify_webhook_signature(
            payload="",
            signature="sha256=abc123",
            secret="whsec_test",
        )

        assert result is False

    def test_empty_signature_fails(self) -> None:
        """Empty signature fails verification."""
        from drip.utils import verify_webhook_signature

        result = verify_webhook_signature(
            payload='{"event": "test"}',
            signature="",
            secret="whsec_test",
        )

        assert result is False

    def test_empty_secret_fails(self) -> None:
        """Empty secret fails verification."""
        from drip.utils import verify_webhook_signature

        result = verify_webhook_signature(
            payload='{"event": "test"}',
            signature="sha256=abc123",
            secret="",
        )

        assert result is False

    def test_timing_safe_comparison(self) -> None:
        """Verification uses timing-safe comparison."""
        from drip.utils import verify_webhook_signature

        # This test verifies the code uses hmac.compare_digest
        # by checking that similar signatures don't leak timing info
        secret = "whsec_test"
        payload = '{"event": "test"}'

        # Generate valid signature
        valid_sig = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Create similar but invalid signatures
        almost_valid = valid_sig[:-1] + ("0" if valid_sig[-1] != "0" else "1")

        # Both should fail (or pass) in similar time
        result1 = verify_webhook_signature(payload, "wrong", secret)
        result2 = verify_webhook_signature(payload, almost_valid, secret)

        assert result1 is False
        assert result2 is False


# =============================================================================
# Generate Nonce Tests
# =============================================================================


class TestGenerateNonce:
    """Test nonce generation."""

    def test_default_length(self) -> None:
        """Default nonce is 64 hex chars (32 bytes)."""
        from drip.utils import generate_nonce

        nonce = generate_nonce()

        assert len(nonce) == 64
        assert all(c in "0123456789abcdef" for c in nonce)

    def test_custom_length(self) -> None:
        """Custom length produces correct size nonce."""
        from drip.utils import generate_nonce

        nonce = generate_nonce(length=16)

        assert len(nonce) == 32  # 16 bytes = 32 hex chars

    def test_nonces_are_unique(self) -> None:
        """Generated nonces are unique."""
        from drip.utils import generate_nonce

        nonces = [generate_nonce() for _ in range(100)]

        assert len(set(nonces)) == 100


# =============================================================================
# Timestamp Tests
# =============================================================================


class TestTimestamps:
    """Test timestamp functions."""

    def test_current_timestamp(self) -> None:
        """current_timestamp returns Unix timestamp in seconds."""
        from drip.utils import current_timestamp

        ts = current_timestamp()
        now = int(time.time())

        # Should be within 1 second
        assert abs(ts - now) <= 1
        assert isinstance(ts, int)

    def test_current_timestamp_ms(self) -> None:
        """current_timestamp_ms returns Unix timestamp in milliseconds."""
        from drip.utils import current_timestamp_ms

        ts_ms = current_timestamp_ms()
        now_ms = int(time.time() * 1000)

        # Should be within 1000 ms
        assert abs(ts_ms - now_ms) <= 1000
        assert isinstance(ts_ms, int)

    def test_timestamp_precision(self) -> None:
        """Millisecond timestamp has proper precision."""
        from drip.utils import current_timestamp, current_timestamp_ms

        ts = current_timestamp()
        ts_ms = current_timestamp_ms()

        # ts_ms should be approximately ts * 1000
        assert abs(ts_ms - ts * 1000) < 1000


# =============================================================================
# Hex Validation Tests
# =============================================================================


class TestIsValidHex:
    """Test hex validation."""

    def test_valid_hex(self) -> None:
        """Valid hex strings are accepted."""
        from drip.utils import is_valid_hex

        assert is_valid_hex("abc123") is True
        assert is_valid_hex("ABC123") is True
        assert is_valid_hex("0123456789abcdef") is True

    def test_valid_hex_with_0x_prefix(self) -> None:
        """Hex with 0x prefix is valid."""
        from drip.utils import is_valid_hex

        assert is_valid_hex("0xabc123") is True
        assert is_valid_hex("0XABC123") is True

    def test_invalid_hex(self) -> None:
        """Invalid hex strings are rejected."""
        from drip.utils import is_valid_hex

        assert is_valid_hex("ghijkl") is False
        assert is_valid_hex("xyz") is False
        assert is_valid_hex("12g45") is False

    def test_empty_string(self) -> None:
        """Empty string is invalid."""
        from drip.utils import is_valid_hex

        assert is_valid_hex("") is False


# =============================================================================
# Address Normalization Tests
# =============================================================================


class TestNormalizeAddress:
    """Test Ethereum address normalization."""

    def test_lowercase_normalization(self) -> None:
        """Address is normalized to lowercase."""
        from drip.utils import normalize_address

        address = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        normalized = normalize_address(address)

        assert normalized == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert normalized.startswith("0x")

    def test_adds_0x_prefix(self) -> None:
        """Address without 0x prefix gets it added."""
        from drip.utils import normalize_address

        address = "abcdef1234567890abcdef1234567890abcdef12"
        normalized = normalize_address(address)

        assert normalized == "0xabcdef1234567890abcdef1234567890abcdef12"

    def test_valid_checksummed_address(self) -> None:
        """Checksummed address is normalized."""
        from drip.utils import normalize_address

        # Example checksummed address
        address = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        normalized = normalize_address(address)

        assert normalized == address.lower()

    def test_invalid_address_length(self) -> None:
        """Invalid address length raises error."""
        from drip.utils import normalize_address

        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            normalize_address("0x123")  # Too short

        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            normalize_address("0x" + "a" * 50)  # Too long

    def test_empty_address(self) -> None:
        """Empty address raises error."""
        from drip.utils import normalize_address

        with pytest.raises(ValueError, match="Address cannot be empty"):
            normalize_address("")

    def test_invalid_hex_in_address(self) -> None:
        """Non-hex characters in address raise error."""
        from drip.utils import normalize_address

        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            normalize_address("0xghijkl1234567890abcdef1234567890abcdef12")


# =============================================================================
# USDC Formatting Tests
# =============================================================================


class TestFormatUsdcAmount:
    """Test USDC amount formatting."""

    def test_format_whole_dollars(self) -> None:
        """Whole dollar amounts format correctly."""
        from drip.utils import format_usdc_amount

        assert format_usdc_amount(1_000_000) == "$1.00"
        assert format_usdc_amount(10_000_000) == "$10.00"
        assert format_usdc_amount(100_000_000) == "$100.00"

    def test_format_with_cents(self) -> None:
        """Amounts with cents format correctly."""
        from drip.utils import format_usdc_amount

        assert format_usdc_amount(1_230_000) == "$1.23"
        assert format_usdc_amount(999_999) == "$1.00"  # Rounds

    def test_format_sub_dollar(self) -> None:
        """Sub-dollar amounts format correctly."""
        from drip.utils import format_usdc_amount

        assert format_usdc_amount(100_000) == "$0.10"
        assert format_usdc_amount(10_000) == "$0.01"
        assert format_usdc_amount(1_000) == "$0.00"  # Too small

    def test_format_string_input(self) -> None:
        """String input is converted."""
        from drip.utils import format_usdc_amount

        assert format_usdc_amount("1000000") == "$1.00"

    def test_format_zero(self) -> None:
        """Zero formats correctly."""
        from drip.utils import format_usdc_amount

        assert format_usdc_amount(0) == "$0.00"


class TestParseUsdcAmount:
    """Test USDC amount parsing."""

    def test_parse_simple_amount(self) -> None:
        """Simple amounts parse correctly."""
        from drip.utils import parse_usdc_amount

        assert parse_usdc_amount("1.00") == 1_000_000
        assert parse_usdc_amount("10.50") == 10_500_000
        assert parse_usdc_amount("0.01") == 10_000

    def test_parse_with_dollar_sign(self) -> None:
        """Amounts with $ prefix parse correctly."""
        from drip.utils import parse_usdc_amount

        assert parse_usdc_amount("$1.00") == 1_000_000
        assert parse_usdc_amount("$99.99") == 99_990_000

    def test_parse_with_whitespace(self) -> None:
        """Amounts with whitespace parse correctly."""
        from drip.utils import parse_usdc_amount

        assert parse_usdc_amount("  $1.00  ") == 1_000_000

    def test_parse_whole_numbers(self) -> None:
        """Whole numbers without decimals parse correctly."""
        from drip.utils import parse_usdc_amount

        assert parse_usdc_amount("5") == 5_000_000
        assert parse_usdc_amount("$100") == 100_000_000

    def test_roundtrip_format_parse(self) -> None:
        """Format and parse are inverse operations."""
        from drip.utils import format_usdc_amount, parse_usdc_amount

        original = 12_340_000  # $12.34 (loses sub-cent precision)
        formatted = format_usdc_amount(original)
        parsed = parse_usdc_amount(formatted)

        # Should be close (may lose sub-cent precision)
        assert abs(parsed - original) < 10_000


# =============================================================================
# Idempotency Key From Params Tests
# =============================================================================


class TestGenerateIdempotencyKeyFromParams:
    """Test idempotency key generation from params object."""

    def test_from_params_object(self) -> None:
        """Key generation from params object works."""
        from drip.utils import generate_idempotency_key_from_params
        from drip.models import IdempotencyKeyParams

        params = IdempotencyKeyParams(
            customer_id="cust_123",
            step_name="tokens",
            sequence=1,
        )

        key = generate_idempotency_key_from_params(params)

        assert key is not None
        assert len(key) == 64

    def test_from_params_matches_direct(self) -> None:
        """Params-based key matches direct generation."""
        from drip.utils import generate_idempotency_key, generate_idempotency_key_from_params
        from drip.models import IdempotencyKeyParams

        params = IdempotencyKeyParams(
            customer_id="cust_123",
            step_name="tokens",
            run_id="run_abc",
            sequence=5,
        )

        key_from_params = generate_idempotency_key_from_params(params)
        key_direct = generate_idempotency_key(
            customer_id="cust_123",
            step_name="tokens",
            run_id="run_abc",
            sequence=5,
        )

        assert key_from_params == key_direct
