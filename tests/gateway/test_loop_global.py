from datetime import datetime
from unittest.mock import MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner(tmp_path, monkeypatch):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    session_key = build_session_key(_make_source())
    session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    setattr(session_entry, "title", "Loop Test")
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    return runner, session_key


@pytest.mark.asyncio
async def test_gateway_loop_start_returns_local_controller_state(tmp_path, monkeypatch):
    runner, session_key = _make_runner(tmp_path, monkeypatch)

    result = await runner._handle_loop_command(
        _make_event("/loop start gateway-test docs/plans/test.md"),
        _make_source(),
        session_key,
    )

    assert isinstance(result, str)
    assert "Loop: gateway-test" in result
    assert "Status: started" in result
    assert (tmp_path / ".hermes" / "loops" / "gateway-test" / "loop.json").exists()


@pytest.mark.asyncio
async def test_gateway_loop_plan_rewrites_to_agent_prompt(tmp_path, monkeypatch):
    runner, session_key = _make_runner(tmp_path, monkeypatch)

    result = await runner._handle_loop_command(
        _make_event("/loop plan gateway-test"),
        _make_source(),
        session_key,
    )

    assert isinstance(result, dict)
    assert result["type"] == "send"
    assert "Start or continue a visible Fruit-Loop project controller" in result["message"]
    assert "Loop command: plan" in result["message"]
