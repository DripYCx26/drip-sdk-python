"""Test LangChain callback handler integration.

This module tests:
- DripCallbackHandler (sync)
- AsyncDripCallbackHandler (async)
- Cost calculation utilities
- LLM, tool, chain, and agent tracking
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Skip entire module if langchain not available
langchain_core = pytest.importorskip("langchain_core")


# =============================================================================
# Cost Calculation Tests
# =============================================================================


class TestCostCalculation:
    """Test cost calculation utilities."""

    def test_get_model_pricing_openai(self) -> None:
        """get_model_pricing returns OpenAI pricing."""
        from drip.integrations.langchain import get_model_pricing

        pricing = get_model_pricing("gpt-4")
        assert pricing is not None
        assert "input" in pricing
        assert "output" in pricing
        assert pricing["input"] > 0
        assert pricing["output"] > 0

    def test_get_model_pricing_anthropic(self) -> None:
        """get_model_pricing returns Anthropic pricing."""
        from drip.integrations.langchain import get_model_pricing

        pricing = get_model_pricing("claude-3-opus")
        assert pricing is not None
        assert pricing["input"] > 0
        assert pricing["output"] > 0

    def test_get_model_pricing_unknown(self) -> None:
        """get_model_pricing returns None for unknown models."""
        from drip.integrations.langchain import get_model_pricing

        pricing = get_model_pricing("unknown-model-xyz")
        assert pricing is None

    def test_calculate_cost(self) -> None:
        """calculate_cost computes correct cost."""
        from drip.integrations.langchain import calculate_cost

        # GPT-4: $30/1M input, $60/1M output
        cost = calculate_cost("gpt-4", input_tokens=1000, output_tokens=500)
        assert cost is not None
        # 1000 * 30/1M + 500 * 60/1M = 0.03 + 0.03 = 0.06
        assert cost == pytest.approx(0.06, rel=0.01)

    def test_calculate_cost_unknown_model(self) -> None:
        """calculate_cost returns None for unknown models."""
        from drip.integrations.langchain import calculate_cost

        cost = calculate_cost("unknown-model", input_tokens=1000, output_tokens=500)
        assert cost is None


# =============================================================================
# DripCallbackHandler Initialization Tests
# =============================================================================


class TestDripCallbackHandlerInit:
    """Test DripCallbackHandler initialization."""

    def test_handler_initialization(self) -> None:
        """Handler initializes with correct parameters."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
                workflow="test-workflow",
            )

            assert handler._customer_id == "cus_123"
            assert handler._workflow == "test-workflow"

    def test_handler_customer_id_property(self) -> None:
        """Handler customer_id property works."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            assert handler.customer_id == "cus_123"

            handler.customer_id = "cus_456"
            assert handler.customer_id == "cus_456"

    def test_handler_customer_id_raises_if_not_set(self) -> None:
        """Handler raises if customer_id not set."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(api_key="drip_sk_test")

            with pytest.raises(ValueError, match="customer_id must be set"):
                _ = handler.customer_id


# =============================================================================
# LLM Callback Tests
# =============================================================================


class TestLLMCallbacks:
    """Test LLM callback tracking."""

    def test_on_llm_start_tracks_call(
        self,
        mock_serialized_llm: dict[str, Any],
    ) -> None:
        """on_llm_start tracks LLM call."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            handler.on_llm_start(
                serialized=mock_serialized_llm,
                prompts=["Hello, world!"],
                run_id=run_id,
            )

            assert str(run_id) in handler._llm_calls
            assert handler._llm_calls[str(run_id)].model == "gpt-4"

    def test_on_llm_end_emits_event(
        self,
        mock_serialized_llm: dict[str, Any],
        mock_llm_response: MagicMock,
    ) -> None:
        """on_llm_end emits completion event."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            # Start and end
            handler.on_llm_start(
                serialized=mock_serialized_llm,
                prompts=["Hello"],
                run_id=run_id,
            )
            handler.on_llm_end(
                response=mock_llm_response,
                run_id=run_id,
            )

            # Should have emitted event
            mock_client.emit_event.assert_called()
            call_args = mock_client.emit_event.call_args
            assert call_args.kwargs["event_type"] == "llm.completion"

    def test_on_llm_error_emits_error_event(
        self,
        mock_serialized_llm: dict[str, Any],
    ) -> None:
        """on_llm_error emits error event."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
                emit_on_error=True,
            )

            run_id = uuid.uuid4()

            handler.on_llm_start(
                serialized=mock_serialized_llm,
                prompts=["Hello"],
                run_id=run_id,
            )
            handler.on_llm_error(
                error=ValueError("Test error"),
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()
            call_args = mock_client.emit_event.call_args
            assert call_args.kwargs["event_type"] == "llm.error"


# =============================================================================
# Tool Callback Tests
# =============================================================================


class TestToolCallbacks:
    """Test tool callback tracking."""

    def test_on_tool_start_tracks_call(
        self,
        mock_serialized_tool: dict[str, Any],
    ) -> None:
        """on_tool_start tracks tool call."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            handler.on_tool_start(
                serialized=mock_serialized_tool,
                input_str="2 + 2",
                run_id=run_id,
            )

            assert str(run_id) in handler._tool_calls
            assert handler._tool_calls[str(run_id)].tool_name == "calculator"

    def test_on_tool_end_emits_event(
        self,
        mock_serialized_tool: dict[str, Any],
    ) -> None:
        """on_tool_end emits tool call event."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            handler.on_tool_start(
                serialized=mock_serialized_tool,
                input_str="2 + 2",
                run_id=run_id,
            )
            handler.on_tool_end(
                output="4",
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()
            call_args = mock_client.emit_event.call_args
            assert call_args.kwargs["event_type"] == "tool.call"


# =============================================================================
# Chain Callback Tests
# =============================================================================


class TestChainCallbacks:
    """Test chain callback tracking."""

    def test_on_chain_start_tracks_execution(
        self,
        mock_serialized_chain: dict[str, Any],
    ) -> None:
        """on_chain_start tracks chain execution."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            handler.on_chain_start(
                serialized=mock_serialized_chain,
                inputs={"query": "test"},
                run_id=run_id,
            )

            assert str(run_id) in handler._chain_calls
            assert handler._chain_calls[str(run_id)].chain_type == "LLMChain"

    def test_on_chain_end_emits_event(
        self,
        mock_serialized_chain: dict[str, Any],
    ) -> None:
        """on_chain_end emits chain execution event."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            handler.on_chain_start(
                serialized=mock_serialized_chain,
                inputs={"query": "test"},
                run_id=run_id,
            )
            handler.on_chain_end(
                outputs={"result": "answer"},
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()
            call_args = mock_client.emit_event.call_args
            assert call_args.kwargs["event_type"] == "chain.execution"


# =============================================================================
# Agent Callback Tests
# =============================================================================


class TestAgentCallbacks:
    """Test agent callback tracking."""

    def test_on_agent_action_tracks_action(self) -> None:
        """on_agent_action tracks agent action."""
        from drip.integrations.langchain import DripCallbackHandler
        from langchain_core.agents import AgentAction

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            action = AgentAction(
                tool="search",
                tool_input="python tutorial",
                log="Searching for python tutorial",
            )

            handler.on_agent_action(action=action, run_id=run_id)

            assert str(run_id) in handler._agent_calls
            assert len(handler._agent_calls[str(run_id)].actions) == 1

    def test_on_agent_finish_emits_event(self) -> None:
        """on_agent_finish emits agent finish event."""
        from drip.integrations.langchain import DripCallbackHandler
        from langchain_core.agents import AgentAction, AgentFinish

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            # Simulate agent taking action
            action = AgentAction(
                tool="search",
                tool_input="test",
                log="Searching",
            )
            handler.on_agent_action(action=action, run_id=run_id)

            # Finish
            finish = AgentFinish(
                return_values={"output": "Done"},
                log="Task completed",
            )
            handler.on_agent_finish(finish=finish, run_id=run_id)

            # Check emit_event was called with agent.finish
            calls = mock_client.emit_event.call_args_list
            event_types = [call.kwargs.get("event_type") for call in calls]
            assert "agent.finish" in event_types


# =============================================================================
# Run Management Tests
# =============================================================================


class TestRunManagement:
    """Test run management in callback handler."""

    def test_start_run_creates_run(self) -> None:
        """start_run creates a new run."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.record_run.return_value = MagicMock(run=MagicMock(id="run_123"))

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = handler.start_run()

            assert run_id == "run_123"
            assert handler.run_id == "run_123"

    def test_end_run_ends_run(self) -> None:
        """end_run ends the current run."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.record_run.return_value = MagicMock(run=MagicMock(id="run_123"))
        mock_client.end_run.return_value = MagicMock()

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            handler.start_run()
            handler.end_run(status="COMPLETED")

            mock_client.end_run.assert_called_once()
            assert handler.run_id is None

    def test_auto_create_run(self) -> None:
        """Handler auto-creates run when needed."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_auto_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
                auto_create_run=True,
            )

            # Emit an event without explicitly starting run
            run_id = uuid.uuid4()
            handler.on_tool_start(
                serialized={"name": "test_tool"},
                input_str="test",
                run_id=run_id,
            )
            handler.on_tool_end(output="result", run_id=run_id)

            # Should have auto-created a run
            mock_client.start_run.assert_called()


# =============================================================================
# Async Handler Tests
# =============================================================================


class TestAsyncDripCallbackHandler:
    """Test AsyncDripCallbackHandler."""

    def test_async_handler_initialization(self) -> None:
        """Async handler initializes correctly."""
        from drip.integrations.langchain import AsyncDripCallbackHandler

        with patch("drip.client.AsyncDrip"):
            handler = AsyncDripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
                workflow="test-workflow",
            )

            assert handler._customer_id == "cus_123"
            assert handler._workflow == "test-workflow"

    @pytest.mark.asyncio
    async def test_async_on_llm_start(
        self,
        mock_serialized_llm: dict[str, Any],
    ) -> None:
        """Async on_llm_start tracks call."""
        from drip.integrations.langchain import AsyncDripCallbackHandler

        with patch("drip.client.AsyncDrip"):
            handler = AsyncDripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            await handler.on_llm_start(
                serialized=mock_serialized_llm,
                prompts=["Hello, world!"],
                run_id=run_id,
            )

            assert str(run_id) in handler._llm_calls

    @pytest.mark.asyncio
    async def test_async_on_llm_end(
        self,
        mock_serialized_llm: dict[str, Any],
        mock_llm_response: MagicMock,
    ) -> None:
        """Async on_llm_end emits event."""
        from drip.integrations.langchain import AsyncDripCallbackHandler

        mock_client = AsyncMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.AsyncDrip", return_value=mock_client):
            handler = AsyncDripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            await handler.on_llm_start(
                serialized=mock_serialized_llm,
                prompts=["Hello"],
                run_id=run_id,
            )
            await handler.on_llm_end(
                response=mock_llm_response,
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()

    @pytest.mark.asyncio
    async def test_async_on_tool_callbacks(
        self,
        mock_serialized_tool: dict[str, Any],
    ) -> None:
        """Async tool callbacks work."""
        from drip.integrations.langchain import AsyncDripCallbackHandler

        mock_client = AsyncMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.AsyncDrip", return_value=mock_client):
            handler = AsyncDripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            await handler.on_tool_start(
                serialized=mock_serialized_tool,
                input_str="2 + 2",
                run_id=run_id,
            )
            await handler.on_tool_end(
                output="4",
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()


# =============================================================================
# Retriever Callback Tests
# =============================================================================


class TestRetrieverCallbacks:
    """Test retriever callback tracking."""

    def test_on_retriever_start_tracks_query(self) -> None:
        """on_retriever_start tracks retriever query."""
        from drip.integrations.langchain import DripCallbackHandler

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            handler.on_retriever_start(
                serialized={"name": "VectorStore"},
                query="What is Python?",
                run_id=run_id,
            )

            assert str(run_id) in handler._tool_calls
            assert "retriever:VectorStore" in handler._tool_calls[str(run_id)].tool_name

    def test_on_retriever_end_emits_event(self) -> None:
        """on_retriever_end emits retriever event."""
        from drip.integrations.langchain import DripCallbackHandler
        from langchain_core.documents import Document

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            handler.on_retriever_start(
                serialized={"name": "VectorStore"},
                query="What is Python?",
                run_id=run_id,
            )

            documents = [
                Document(page_content="Python is a programming language."),
                Document(page_content="Python is easy to learn."),
            ]

            handler.on_retriever_end(
                documents=documents,
                run_id=run_id,
            )

            mock_client.emit_event.assert_called()
            call_args = mock_client.emit_event.call_args
            assert call_args.kwargs["event_type"] == "retriever.query"
            assert call_args.kwargs["quantity"] == 2  # 2 documents


# =============================================================================
# Chat Model Callback Tests
# =============================================================================


class TestChatModelCallbacks:
    """Test chat model callback tracking."""

    def test_on_chat_model_start_tracks_call(self) -> None:
        """on_chat_model_start tracks chat model call."""
        from drip.integrations.langchain import DripCallbackHandler
        from langchain_core.messages import HumanMessage

        with patch("drip.client.Drip"):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()
            messages = [[HumanMessage(content="Hello, Claude!")]]

            handler.on_chat_model_start(
                serialized={"name": "ChatAnthropic", "id": ["anthropic", "claude-3-opus"]},
                messages=messages,
                run_id=run_id,
            )

            assert str(run_id) in handler._llm_calls
            assert handler._llm_calls[str(run_id)].model == "ChatAnthropic"


# =============================================================================
# Metadata and Idempotency Tests
# =============================================================================


class TestMetadataAndIdempotency:
    """Test metadata and idempotency key handling."""

    def test_handler_includes_base_metadata(self) -> None:
        """Handler includes base metadata in events."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
                metadata={"app": "test-app", "version": "1.0"},
            )

            run_id = uuid.uuid4()

            handler.on_tool_start(
                serialized={"name": "calculator"},
                input_str="2+2",
                run_id=run_id,
            )
            handler.on_tool_end(output="4", run_id=run_id)

            call_args = mock_client.emit_event.call_args
            metadata = call_args.kwargs.get("metadata", {})
            assert metadata.get("app") == "test-app"
            assert metadata.get("version") == "1.0"

    def test_handler_generates_idempotency_keys(self) -> None:
        """Handler generates idempotency keys for events."""
        from drip.integrations.langchain import DripCallbackHandler

        mock_client = MagicMock()
        mock_client.start_run.return_value = MagicMock(id="run_123")
        mock_client.emit_event.return_value = MagicMock(id="evt_123")

        with patch("drip.client.Drip", return_value=mock_client):
            handler = DripCallbackHandler(
                api_key="drip_sk_test",
                customer_id="cus_123",
            )

            run_id = uuid.uuid4()

            handler.on_tool_start(
                serialized={"name": "calculator"},
                input_str="2+2",
                run_id=run_id,
            )
            handler.on_tool_end(output="4", run_id=run_id)

            call_args = mock_client.emit_event.call_args
            idempotency_key = call_args.kwargs.get("idempotency_key")
            assert idempotency_key is not None
