"""Test SDK resilience features: rate limiting, circuit breaker, retries.

This module tests the resilience patterns implemented in the Drip SDK:
- RateLimiter: Token bucket rate limiting
- CircuitBreaker: Failure isolation pattern
- RetryConfig: Exponential backoff retry logic
- ResilienceManager: Combined resilience management
- MetricsCollector: Request metrics tracking
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import respx
from httpx import Response

if TYPE_CHECKING:
    from drip import Drip


# =============================================================================
# Rate Limiter Tests
# =============================================================================


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_rate_limiter_allows_within_burst(self) -> None:
        """Rate limiter allows requests within burst size."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=10.0,
            burst_size=5,
            enabled=True,
        )
        limiter = RateLimiter(config)

        # Should allow burst_size requests immediately
        for _ in range(5):
            assert limiter.acquire(timeout=0.01) is True

    def test_rate_limiter_blocks_over_burst(self) -> None:
        """Rate limiter blocks requests over burst limit."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=10.0,
            burst_size=3,
            enabled=True,
        )
        limiter = RateLimiter(config)

        # Exhaust burst
        for _ in range(3):
            limiter.acquire(timeout=0.01)

        # Next request should fail with 0 timeout
        assert limiter.acquire(timeout=0) is False

    def test_rate_limiter_refills_tokens(self) -> None:
        """Rate limiter refills tokens over time."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=100.0,  # 100 per second = 1 per 10ms
            burst_size=1,
            enabled=True,
        )
        limiter = RateLimiter(config)

        # Use the one token
        assert limiter.acquire(timeout=0) is True
        assert limiter.acquire(timeout=0) is False

        # Wait for refill
        time.sleep(0.02)

        # Should have tokens again
        assert limiter.acquire(timeout=0) is True

    def test_rate_limiter_disabled(self) -> None:
        """Rate limiter allows all requests when disabled."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=1.0,
            burst_size=1,
            enabled=False,
        )
        limiter = RateLimiter(config)

        # Should allow many requests even with burst_size=1
        for _ in range(100):
            assert limiter.acquire(timeout=0) is True

    def test_rate_limiter_available_tokens(self) -> None:
        """Rate limiter reports available tokens correctly."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=10.0,
            burst_size=10,
            enabled=True,
        )
        limiter = RateLimiter(config)

        assert limiter.available_tokens == 10.0

        limiter.acquire(timeout=0)
        assert limiter.available_tokens == 9.0

    @pytest.mark.asyncio
    async def test_rate_limiter_async_acquire(self) -> None:
        """Rate limiter async acquire works correctly."""
        from drip.resilience import RateLimiter, RateLimiterConfig

        config = RateLimiterConfig(
            requests_per_second=100.0,
            burst_size=5,
            enabled=True,
        )
        limiter = RateLimiter(config)

        # Async acquire should work
        for _ in range(5):
            assert await limiter.acquire_async(timeout=0.01) is True


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    def test_circuit_breaker_starts_closed(self) -> None:
        """Circuit breaker starts in closed state."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

        config = CircuitBreakerConfig(failure_threshold=3, enabled=True)
        cb = CircuitBreaker("test", config)

        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_circuit_breaker_opens_on_failures(self) -> None:
        """Circuit breaker opens after threshold failures."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

        config = CircuitBreakerConfig(failure_threshold=3, enabled=True)
        cb = CircuitBreaker("test", config)

        # Record failures up to threshold
        for _ in range(3):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_circuit_breaker_half_open_after_timeout(self) -> None:
        """Circuit breaker enters half-open after reset timeout."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

        config = CircuitBreakerConfig(
            failure_threshold=2,
            timeout=0.05,  # 50ms timeout
            enabled=True,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.06)

        # Should transition to half-open on next request check
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_closes_on_success_in_half_open(self) -> None:
        """Circuit breaker closes on success in half-open state."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

        config = CircuitBreakerConfig(
            failure_threshold=2,
            success_threshold=1,
            timeout=0.05,
            enabled=True,
        )
        cb = CircuitBreaker("test", config)

        # Open and wait for half-open
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # Trigger half-open

        # Record success
        cb.record_success()

        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_reopens_on_failure_in_half_open(self) -> None:
        """Circuit breaker reopens on failure in half-open state."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

        config = CircuitBreakerConfig(
            failure_threshold=2,
            timeout=0.05,
            enabled=True,
        )
        cb = CircuitBreaker("test", config)

        # Open and wait for half-open
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # Trigger half-open
        assert cb.state == CircuitState.HALF_OPEN

        # Record failure in half-open
        cb.record_failure()

        assert cb.state == CircuitState.OPEN

    def test_circuit_breaker_disabled(self) -> None:
        """Circuit breaker allows all requests when disabled."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig

        config = CircuitBreakerConfig(failure_threshold=1, enabled=False)
        cb = CircuitBreaker("test", config)

        # Should allow requests even after failures
        for _ in range(10):
            cb.record_failure()

        assert cb.allow_request() is True

    def test_circuit_breaker_time_until_retry(self) -> None:
        """Circuit breaker reports time until retry."""
        from drip.resilience import CircuitBreaker, CircuitBreakerConfig

        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout=1.0,
            enabled=True,
        )
        cb = CircuitBreaker("test", config)

        cb.record_failure()

        time_until = cb.get_time_until_retry()
        assert 0 < time_until <= 1.0

    def test_circuit_breaker_as_decorator(self) -> None:
        """Circuit breaker can be used as decorator."""
        from drip.resilience import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitBreakerOpen,
        )

        config = CircuitBreakerConfig(failure_threshold=2, enabled=True)
        cb = CircuitBreaker("test", config)

        call_count = 0

        @cb
        def failing_function() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        # First two calls should fail and open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                failing_function()

        # Third call should be blocked by circuit breaker
        with pytest.raises(CircuitBreakerOpen):
            failing_function()

        assert call_count == 2


# =============================================================================
# Retry Tests
# =============================================================================


class TestRetry:
    """Test retry functionality."""

    def test_calculate_backoff(self) -> None:
        """Backoff calculation is correct."""
        from drip.resilience import RetryConfig, calculate_backoff

        config = RetryConfig(
            base_delay=0.1,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=0.0,  # Disable jitter for predictable tests
        )

        # First attempt: 0.1 * 2^0 = 0.1
        assert calculate_backoff(0, config) == pytest.approx(0.1)

        # Second attempt: 0.1 * 2^1 = 0.2
        assert calculate_backoff(1, config) == pytest.approx(0.2)

        # Third attempt: 0.1 * 2^2 = 0.4
        assert calculate_backoff(2, config) == pytest.approx(0.4)

    def test_calculate_backoff_respects_max_delay(self) -> None:
        """Backoff is capped at max_delay."""
        from drip.resilience import RetryConfig, calculate_backoff

        config = RetryConfig(
            base_delay=1.0,
            max_delay=5.0,
            exponential_base=2.0,
            jitter=0.0,
        )

        # Attempt 10: 1.0 * 2^10 = 1024, but capped at 5.0
        assert calculate_backoff(10, config) == pytest.approx(5.0)

    def test_calculate_backoff_with_jitter(self) -> None:
        """Backoff includes jitter."""
        from drip.resilience import RetryConfig, calculate_backoff

        config = RetryConfig(
            base_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=0.5,  # 50% jitter
        )

        # With jitter, results should vary
        results = [calculate_backoff(0, config) for _ in range(10)]

        # Base is 1.0, jitter is 0.5, so range is [0.5, 1.5]
        assert all(0.5 <= r <= 1.5 for r in results)

    def test_with_retry_decorator(self) -> None:
        """Retry decorator retries on failure."""
        from drip.resilience import RetryConfig, with_retry

        config = RetryConfig(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ValueError,),
            enabled=True,
        )

        call_count = 0

        @with_retry(config)
        def flaky_function() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Flaky!")
            return "success"

        result = flaky_function()

        assert result == "success"
        assert call_count == 3

    def test_with_retry_exhausted(self) -> None:
        """Retry decorator raises RetryExhausted when exhausted."""
        from drip.resilience import RetryConfig, RetryExhausted, with_retry

        config = RetryConfig(
            max_retries=2,
            base_delay=0.001,
            retryable_exceptions=(ValueError,),
            enabled=True,
        )

        @with_retry(config)
        def always_fails() -> str:
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted) as exc_info:
            always_fails()

        assert exc_info.value.attempts == 3  # Initial + 2 retries

    def test_with_retry_disabled(self) -> None:
        """Retry decorator passes through when disabled."""
        from drip.resilience import RetryConfig, with_retry

        config = RetryConfig(enabled=False)

        call_count = 0

        @with_retry(config)
        def failing_function() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Fails")

        with pytest.raises(ValueError):
            failing_function()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_async(self) -> None:
        """Async retry decorator retries on failure."""
        from drip.resilience import RetryConfig, with_retry_async

        config = RetryConfig(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ValueError,),
            enabled=True,
        )

        call_count = 0

        @with_retry_async(config)
        async def async_flaky_function() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Flaky!")
            return "success"

        result = await async_flaky_function()

        assert result == "success"
        assert call_count == 2


# =============================================================================
# Metrics Collector Tests
# =============================================================================


class TestMetricsCollector:
    """Test metrics collector functionality."""

    def test_metrics_collector_records_requests(self) -> None:
        """Metrics collector records request metrics."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector(window_size=100)

        collector.record(
            RequestMetrics(
                method="POST",
                endpoint="/charges",
                status_code=200,
                duration_ms=50.0,
                success=True,
            )
        )

        summary = collector.get_summary()

        assert summary["total_requests"] == 1
        assert summary["total_successes"] == 1
        assert summary["avg_latency_ms"] == 50.0

    def test_metrics_collector_tracks_failures(self) -> None:
        """Metrics collector tracks failures."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector()

        collector.record(
            RequestMetrics(
                method="POST",
                endpoint="/charges",
                status_code=500,
                duration_ms=100.0,
                success=False,
                error="InternalServerError",
            )
        )

        summary = collector.get_summary()

        assert summary["total_failures"] == 1
        assert "InternalServerError" in summary["errors_by_type"]

    def test_metrics_collector_calculates_percentiles(self) -> None:
        """Metrics collector calculates latency percentiles."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector()

        # Add requests with varying latencies
        latencies = list(range(1, 101))  # 1ms to 100ms
        for latency in latencies:
            collector.record(
                RequestMetrics(
                    method="GET",
                    endpoint="/health",
                    status_code=200,
                    duration_ms=float(latency),
                    success=True,
                )
            )

        summary = collector.get_summary()

        assert summary["p50_latency_ms"] == pytest.approx(50.0, rel=0.1)
        assert summary["p95_latency_ms"] == pytest.approx(95.0, rel=0.1)

    def test_metrics_collector_groups_by_endpoint(self) -> None:
        """Metrics collector groups requests by endpoint."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector()

        for _ in range(5):
            collector.record(
                RequestMetrics(
                    method="POST",
                    endpoint="/charges",
                    status_code=200,
                    duration_ms=50.0,
                    success=True,
                )
            )

        for _ in range(3):
            collector.record(
                RequestMetrics(
                    method="GET",
                    endpoint="/customers",
                    status_code=200,
                    duration_ms=30.0,
                    success=True,
                )
            )

        summary = collector.get_summary()

        assert summary["requests_by_endpoint"]["/charges"] == 5
        assert summary["requests_by_endpoint"]["/customers"] == 3

    def test_metrics_collector_reset(self) -> None:
        """Metrics collector can be reset."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector()

        collector.record(
            RequestMetrics(
                method="GET",
                endpoint="/health",
                status_code=200,
                duration_ms=10.0,
                success=True,
            )
        )

        collector.reset()

        summary = collector.get_summary()
        assert summary["total_requests"] == 0

    def test_metrics_collector_window_size(self) -> None:
        """Metrics collector respects window size."""
        from drip.resilience import MetricsCollector, RequestMetrics

        collector = MetricsCollector(window_size=5)

        # Add 10 requests
        for i in range(10):
            collector.record(
                RequestMetrics(
                    method="GET",
                    endpoint="/health",
                    status_code=200,
                    duration_ms=float(i),
                    success=True,
                )
            )

        summary = collector.get_summary()

        # Window should only contain last 5
        assert summary["window_size"] == 5
        # Total should still count all
        assert summary["total_requests"] == 10


# =============================================================================
# Resilience Manager Tests
# =============================================================================


class TestResilienceManager:
    """Test resilience manager functionality."""

    def test_resilience_manager_execute(self) -> None:
        """Resilience manager executes functions with protection."""
        from drip.resilience import ResilienceConfig, ResilienceManager

        config = ResilienceConfig.default()
        manager = ResilienceManager(config)

        def simple_function() -> str:
            return "success"

        result = manager.execute(simple_function, method="GET", endpoint="/test")

        assert result == "success"

    def test_resilience_manager_tracks_metrics(self) -> None:
        """Resilience manager tracks request metrics."""
        from drip.resilience import ResilienceConfig, ResilienceManager

        config = ResilienceConfig.default()
        manager = ResilienceManager(config)

        manager.execute(lambda: "ok", method="GET", endpoint="/health")

        metrics = manager.get_metrics()

        assert metrics is not None
        assert metrics["total_requests"] == 1
        assert metrics["total_successes"] == 1

    def test_resilience_manager_get_health(self) -> None:
        """Resilience manager reports health status."""
        from drip.resilience import ResilienceConfig, ResilienceManager

        config = ResilienceConfig.default()
        manager = ResilienceManager(config)

        health = manager.get_health()

        assert health is not None
        assert "circuit_breaker" in health
        assert "rate_limiter" in health
        assert health["circuit_breaker"]["state"] == "closed"

    def test_resilience_manager_with_retries(self) -> None:
        """Resilience manager retries on transient failures."""
        from drip.resilience import ResilienceConfig, ResilienceManager, RetryConfig

        config = ResilienceConfig(
            retry=RetryConfig(
                max_retries=2,
                base_delay=0.001,
                retryable_exceptions=(ValueError,),
                enabled=True,
            ),
        )
        manager = ResilienceManager(config)

        call_count = 0

        def flaky_function() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Transient error")
            return "success"

        result = manager.execute(flaky_function)

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_resilience_manager_execute_async(self) -> None:
        """Resilience manager executes async functions."""
        from drip.resilience import ResilienceConfig, ResilienceManager

        config = ResilienceConfig.default()
        manager = ResilienceManager(config)

        async def async_function() -> str:
            await asyncio.sleep(0.001)
            return "async success"

        result = await manager.execute_async(async_function, method="GET", endpoint="/test")

        assert result == "async success"


# =============================================================================
# Resilience Configuration Tests
# =============================================================================


class TestResilienceConfig:
    """Test resilience configuration presets."""

    def test_default_config(self) -> None:
        """Default configuration has sensible defaults."""
        from drip.resilience import ResilienceConfig

        config = ResilienceConfig.default()

        assert config.rate_limiter.enabled is True
        assert config.retry.enabled is True
        assert config.circuit_breaker.enabled is True
        assert config.collect_metrics is True

    def test_disabled_config(self) -> None:
        """Disabled configuration disables all features."""
        from drip.resilience import ResilienceConfig

        config = ResilienceConfig.disabled()

        assert config.rate_limiter.enabled is False
        assert config.retry.enabled is False
        assert config.circuit_breaker.enabled is False
        assert config.collect_metrics is False

    def test_high_throughput_config(self) -> None:
        """High throughput configuration optimizes for speed."""
        from drip.resilience import ResilienceConfig

        config = ResilienceConfig.high_throughput()

        # Higher rate limits
        assert config.rate_limiter.requests_per_second >= 1000

        # Fewer retries
        assert config.retry.max_retries <= 2

        # Higher failure threshold
        assert config.circuit_breaker.failure_threshold >= 10


# =============================================================================
# Client Integration Tests
# =============================================================================


class TestClientWithResilience:
    """Test Drip client with resilience enabled."""

    def test_client_with_resilience_enabled(
        self,
        api_key: str,
        mock_api: respx.MockRouter,
    ) -> None:
        """Client works with resilience enabled."""
        from drip import Drip
        from drip.resilience import ResilienceConfig

        mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))

        client = Drip(
            api_key=api_key,
            base_url="https://api.drip.dev/v1",
            resilience=ResilienceConfig.default(),
        )

        try:
            result = client.ping()
            assert result["ok"] is True
        finally:
            client.close()

    def test_client_resilience_disabled(
        self,
        api_key: str,
        mock_api: respx.MockRouter,
    ) -> None:
        """Client works with resilience disabled."""
        from drip import Drip

        mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))

        client = Drip(
            api_key=api_key,
            base_url="https://api.drip.dev/v1",
            resilience=None,
        )

        try:
            result = client.ping()
            assert result["ok"] is True
        finally:
            client.close()

    def test_client_exposes_resilience_metrics(
        self,
        api_key: str,
        mock_api: respx.MockRouter,
    ) -> None:
        """Client exposes resilience metrics."""
        from drip import Drip
        from drip.resilience import ResilienceConfig

        mock_api.get("/health").mock(return_value=Response(200, json={"ok": True}))

        client = Drip(
            api_key=api_key,
            base_url="https://api.drip.dev/v1",
            resilience=ResilienceConfig.default(),
        )

        try:
            client.ping()

            if client._resilience:
                metrics = client._resilience.get_metrics()
                assert metrics is not None
                assert metrics["total_requests"] >= 1
        finally:
            client.close()


# =============================================================================
# CircuitBreakerOpen Exception Tests
# =============================================================================


class TestCircuitBreakerOpenException:
    """Test CircuitBreakerOpen exception."""

    def test_exception_message(self) -> None:
        """Exception has informative message."""
        from drip.resilience import CircuitBreakerOpen

        exc = CircuitBreakerOpen("test_circuit", 5.5)

        assert exc.circuit_name == "test_circuit"
        assert exc.time_until_retry == 5.5
        assert "test_circuit" in str(exc)
        assert "5.5" in str(exc)


# =============================================================================
# RetryExhausted Exception Tests
# =============================================================================


class TestRetryExhaustedException:
    """Test RetryExhausted exception."""

    def test_exception_attributes(self) -> None:
        """Exception has correct attributes."""
        from drip.resilience import RetryExhausted

        original_error = ValueError("Original error")
        exc = RetryExhausted(3, original_error)

        assert exc.attempts == 3
        assert exc.last_exception is original_error
        assert "3 attempts" in str(exc)
