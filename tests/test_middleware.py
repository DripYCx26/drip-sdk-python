"""Test framework middleware integrations.

This module tests:
- FastAPI middleware (DripMiddleware)
- FastAPI decorators (with_drip)
- FastAPI dependency injection (get_drip_context)
- Flask middleware (DripFlaskMiddleware)
- Flask decorators (drip_middleware)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip entire module if frameworks not available
fastapi = pytest.importorskip("fastapi")
flask_module = pytest.importorskip("flask")


# =============================================================================
# FastAPI Middleware Tests
# =============================================================================


class TestFastAPIMiddleware:
    """Test FastAPI middleware integration."""

    def test_fastapi_middleware_import(self) -> None:
        """FastAPI middleware can be imported."""
        from drip.middleware.fastapi import (
            DripMiddleware,
            get_drip_context,
            has_drip_context,
            with_drip,
        )

        assert DripMiddleware is not None
        assert get_drip_context is not None
        assert has_drip_context is not None
        assert with_drip is not None

    def test_fastapi_middleware_initialization(
        self,
        api_key: str,
        base_url: str,
    ) -> None:
        """FastAPI middleware initializes correctly."""
        from fastapi import FastAPI
        from drip.middleware.fastapi import DripMiddleware

        app = FastAPI()

        # Should not raise
        app.add_middleware(
            DripMiddleware,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        assert len(app.user_middleware) >= 1

    def test_fastapi_middleware_excludes_paths(
        self,
        api_key: str,
        base_url: str,
    ) -> None:
        """FastAPI middleware respects exclude_paths."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import DripMiddleware

        app = FastAPI()

        app.add_middleware(
            DripMiddleware,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
            exclude_paths=["/health", "/metrics"],
            skip_in_development=True,
        )

        @app.get("/health")
        def health() -> dict[str, bool]:
            return {"ok": True}

        client = TestClient(app)

        # Excluded path should work without billing
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    @patch("drip.middleware.core.process_request_async")
    def test_fastapi_middleware_processes_requests(
        self,
        mock_process: AsyncMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """FastAPI middleware processes non-excluded requests."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import DripMiddleware
        from drip.middleware.types import DripContext, ProcessResult

        # Mock the process result
        mock_context = MagicMock(spec=DripContext)
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = FastAPI()

        app.add_middleware(
            DripMiddleware,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        @app.get("/api/test")
        def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/api/test")

        assert response.status_code == 200

    def test_fastapi_get_drip_context_raises_without_middleware(self) -> None:
        """get_drip_context raises if middleware not applied."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import get_drip_context

        app = FastAPI()

        @app.get("/test")
        def test_endpoint(request: Request) -> dict[str, str]:
            # This should raise
            get_drip_context(request)
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")

        # Should fail due to missing context
        assert response.status_code == 500

    def test_fastapi_has_drip_context(self) -> None:
        """has_drip_context returns False when context not available."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import has_drip_context

        app = FastAPI()

        @app.get("/test")
        def test_endpoint(request: Request) -> dict[str, bool]:
            return {"has_context": has_drip_context(request)}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert response.json()["has_context"] is False


class TestFastAPIDecorator:
    """Test FastAPI with_drip decorator."""

    @patch("drip.middleware.core.process_request_async")
    def test_with_drip_decorator(
        self,
        mock_process: AsyncMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """with_drip decorator processes requests."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import with_drip
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = FastAPI()

        @app.post("/api/generate")
        @with_drip(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )
        async def generate(request: Request) -> dict[str, str]:
            return {"status": "generated"}

        client = TestClient(app)
        response = client.post("/api/generate")

        assert response.status_code == 200


class TestFastAPIDependency:
    """Test FastAPI dependency injection."""

    @patch("drip.middleware.core.process_request_async")
    def test_create_drip_dependency(
        self,
        mock_process: AsyncMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """create_drip_dependency creates working dependency."""
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import create_drip_dependency
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_context.customer_id = "cus_123"
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = FastAPI()

        charge_api_call = create_drip_dependency(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        @app.post("/api/endpoint")
        async def endpoint(drip: DripContext = Depends(charge_api_call)) -> dict[str, str]:
            return {"customer": drip.customer_id}

        client = TestClient(app)
        response = client.post("/api/endpoint")

        assert response.status_code == 200


# =============================================================================
# Flask Middleware Tests
# =============================================================================


class TestFlaskMiddleware:
    """Test Flask middleware integration."""

    def test_flask_middleware_import(self) -> None:
        """Flask middleware can be imported."""
        from drip.middleware.flask import (
            DripFlaskMiddleware,
            drip_middleware,
            get_drip_context,
            has_drip_context,
        )

        assert DripFlaskMiddleware is not None
        assert drip_middleware is not None
        assert get_drip_context is not None
        assert has_drip_context is not None

    def test_flask_extension_initialization(
        self,
        api_key: str,
        base_url: str,
    ) -> None:
        """Flask extension initializes correctly."""
        from flask import Flask
        from drip.middleware.flask import DripFlaskMiddleware

        app = Flask(__name__)

        # Should not raise
        drip = DripFlaskMiddleware(
            app,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        assert drip is not None

    def test_flask_extension_init_app(
        self,
        api_key: str,
        base_url: str,
    ) -> None:
        """Flask extension supports init_app pattern."""
        from flask import Flask
        from drip.middleware.flask import DripFlaskMiddleware

        app = Flask(__name__)

        drip = DripFlaskMiddleware(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )
        drip.init_app(app)

        assert drip is not None


class TestFlaskDecorator:
    """Test Flask drip_middleware decorator."""

    @patch("drip.middleware.core.process_request_sync")
    def test_drip_middleware_decorator(
        self,
        mock_process: MagicMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """drip_middleware decorator processes requests."""
        from flask import Flask
        from drip.middleware.flask import drip_middleware
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = Flask(__name__)

        @app.route("/api/generate", methods=["POST"])
        @drip_middleware(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )
        def generate() -> dict[str, str]:
            return {"status": "generated"}

        client = app.test_client()
        response = client.post("/api/generate")

        assert response.status_code == 200

    @patch("drip.middleware.core.process_request_sync")
    def test_drip_middleware_with_get_context(
        self,
        mock_process: MagicMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """drip_middleware with get_drip_context."""
        from flask import Flask
        from drip.middleware.flask import drip_middleware, get_drip_context
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_context.customer_id = "cus_123"
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = Flask(__name__)

        @app.route("/api/generate", methods=["POST"])
        @drip_middleware(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )
        def generate() -> dict[str, str]:
            drip = get_drip_context()
            return {"customer": drip.customer_id}

        client = app.test_client()
        response = client.post("/api/generate")

        assert response.status_code == 200

    def test_flask_has_drip_context_without_middleware(self) -> None:
        """has_drip_context returns False without middleware."""
        from flask import Flask
        from drip.middleware.flask import has_drip_context

        app = Flask(__name__)

        @app.route("/test")
        def test_endpoint() -> dict[str, bool]:
            return {"has_context": has_drip_context()}

        with app.test_request_context():
            assert has_drip_context() is False

    def test_flask_get_drip_context_raises_without_middleware(self) -> None:
        """get_drip_context raises if middleware not applied."""
        from flask import Flask
        from drip.middleware.flask import get_drip_context

        app = Flask(__name__)

        with app.test_request_context():
            with pytest.raises(ValueError, match="Drip context not found"):
                get_drip_context()


class TestFlaskCreateDecorator:
    """Test Flask create_drip_decorator."""

    @patch("drip.middleware.core.process_request_sync")
    def test_create_drip_decorator(
        self,
        mock_process: MagicMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """create_drip_decorator creates reusable decorator."""
        from flask import Flask
        from drip.middleware.flask import create_drip_decorator
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = Flask(__name__)

        charge_api_call = create_drip_decorator(
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        @app.route("/api/endpoint1")
        @charge_api_call
        def endpoint1() -> dict[str, str]:
            return {"endpoint": "1"}

        @app.route("/api/endpoint2")
        @charge_api_call
        def endpoint2() -> dict[str, str]:
            return {"endpoint": "2"}

        client = app.test_client()

        response1 = client.get("/api/endpoint1")
        assert response1.status_code == 200

        response2 = client.get("/api/endpoint2")
        assert response2.status_code == 200


# =============================================================================
# Middleware Context Tests
# =============================================================================


class TestMiddlewareContext:
    """Test DripContext behavior."""

    def test_drip_context_attributes(self) -> None:
        """DripContext has expected attributes."""
        from drip.middleware.types import DripContext

        context = DripContext(
            customer_id="cus_123",
            charge=None,
            skipped=False,
            metadata={"key": "value"},
        )

        assert context.customer_id == "cus_123"
        assert context.charge is None
        assert context.skipped is False
        assert context.metadata == {"key": "value"}


# =============================================================================
# Middleware Configuration Tests
# =============================================================================


class TestMiddlewareConfig:
    """Test DripMiddlewareConfig."""

    def test_middleware_config_with_callable_quantity(self) -> None:
        """Middleware config accepts callable quantity."""
        from drip.middleware.types import DripMiddlewareConfig

        def dynamic_quantity(request: Any) -> float:
            return 5.0

        config = DripMiddlewareConfig(
            meter="api_calls",
            quantity=dynamic_quantity,
        )

        assert config.meter == "api_calls"
        assert callable(config.quantity)

    def test_middleware_config_with_callable_customer_resolver(self) -> None:
        """Middleware config accepts callable customer resolver."""
        from drip.middleware.types import DripMiddlewareConfig

        def custom_resolver(request: Any) -> str:
            return "cus_custom"

        config = DripMiddlewareConfig(
            meter="api_calls",
            quantity=1,
            customer_resolver=custom_resolver,
        )

        assert callable(config.customer_resolver)

    def test_middleware_config_with_metadata(self) -> None:
        """Middleware config accepts metadata."""
        from drip.middleware.types import DripMiddlewareConfig

        config = DripMiddlewareConfig(
            meter="api_calls",
            quantity=1,
            metadata={"source": "api", "version": "1.0"},
        )

        assert config.metadata == {"source": "api", "version": "1.0"}


# =============================================================================
# Payment Required Response Tests
# =============================================================================


class TestPaymentRequiredResponse:
    """Test 402 Payment Required responses."""

    @patch("drip.middleware.core.process_request_async")
    def test_fastapi_returns_402_when_payment_required(
        self,
        mock_process: AsyncMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """FastAPI returns 402 when payment is required."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import DripMiddleware
        from drip.middleware.types import ProcessResult, PaymentHeaders
        from drip.models import X402PaymentRequest

        mock_payment_request = MagicMock(spec=X402PaymentRequest)
        mock_payment_request.model_dump.return_value = {"amount": "100"}

        mock_headers = MagicMock(spec=PaymentHeaders)
        mock_headers.to_dict.return_value = {"X-Payment-Required": "true"}

        mock_process.return_value = ProcessResult(
            context=None,
            payment_required=True,
            payment_headers=mock_headers,
            payment_request=mock_payment_request,
            error=None,
        )

        app = FastAPI()

        app.add_middleware(
            DripMiddleware,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
        )

        @app.get("/api/test")
        def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/api/test")

        assert response.status_code == 402
        assert "error" in response.json()


# =============================================================================
# Skip in Development Tests
# =============================================================================


class TestSkipInDevelopment:
    """Test skip_in_development behavior."""

    @patch("drip.middleware.core.process_request_async")
    def test_fastapi_skips_in_development(
        self,
        mock_process: AsyncMock,
        api_key: str,
        base_url: str,
    ) -> None:
        """FastAPI middleware can skip billing in development."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from drip.middleware.fastapi import DripMiddleware
        from drip.middleware.types import DripContext, ProcessResult

        mock_context = MagicMock(spec=DripContext)
        mock_context.skipped = True
        mock_process.return_value = ProcessResult(
            context=mock_context,
            payment_required=False,
            payment_headers=None,
            payment_request=None,
            error=None,
        )

        app = FastAPI()

        app.add_middleware(
            DripMiddleware,
            meter="api_calls",
            quantity=1,
            api_key=api_key,
            base_url=base_url,
            skip_in_development=True,
        )

        @app.get("/api/test")
        def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/api/test")

        # Should still work, just skip billing
        assert response.status_code == 200
