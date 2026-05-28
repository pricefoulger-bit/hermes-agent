import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource


@pytest.mark.asyncio
async def test_gateway_view_rewrites_to_agent_prompt(monkeypatch, tmp_path):
    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))

    runner = GatewayRunner(GatewayConfig())

    captured = {}

    async def _capture_agent(self, event, *args, **kwargs):
        captured["text"] = event.text
        return "agent-result"

    monkeypatch.setattr(GatewayRunner, "_is_user_authorized", lambda self, source: True)
    monkeypatch.setattr(GatewayRunner, "_handle_message_with_agent", _capture_agent)

    event = MessageEvent(
        text="/view Hermes UX",
        source=SessionSource(
            platform=Platform.DISCORD,
            chat_id="123",
            chat_type="dm",
            user_id="u1",
            user_name="Price",
        ),
    )

    result = await runner._handle_message(event)

    assert result == "agent-result"
    assert captured["text"].startswith("Produce a Project View for Hermes UX")
    assert "source: discord" in captured["text"]
    assert "### Best next move" in captured["text"]
    assert not captured["text"].startswith("/")
