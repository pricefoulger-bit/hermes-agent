import queue

from cli import HermesCLI


def _make_cli(tmp_path, monkeypatch):
    cli = object.__new__(HermesCLI)
    cli._pending_input = queue.Queue()
    cli._agent_running = False
    cli.session_id = "sess-test"
    cli._pending_title = "Test Session"
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    return cli


def test_loop_command_registered_globally():
    from hermes_cli.commands import resolve_command

    cmd = resolve_command("loop")
    assert cmd is not None
    assert cmd.name == "loop"
    assert cmd.category == "Session"
    assert "run next" in cmd.args_hint
    assert "close" in cmd.subcommands


def test_cli_loop_start_renders_local_controller_state(tmp_path, monkeypatch):
    cli = _make_cli(tmp_path, monkeypatch)
    printed = []
    monkeypatch.setattr("cli._cprint", lambda text: printed.append(str(text)))

    cli._handle_loop_command("/loop start global-test docs/plans/test.md")

    assert printed
    assert "Loop: global-test" in printed[0]
    assert "Status: started" in printed[0]
    assert (tmp_path / ".hermes" / "loops" / "global-test" / "loop.json").exists()
    assert cli._pending_input.empty()


def test_cli_loop_plan_queues_prompt_for_current_agent_session(tmp_path, monkeypatch):
    cli = _make_cli(tmp_path, monkeypatch)
    printed = []
    monkeypatch.setattr("cli._cprint", lambda text: printed.append(str(text)))

    cli._handle_loop_command("/loop plan global-test")

    assert not cli._pending_input.empty()
    queued = cli._pending_input.get_nowait()
    assert "Start or continue a visible Fruit-Loop project controller" in queued
    assert "Loop command: plan" in queued
    assert printed and "Loop prompt queued" in printed[0]


def test_loop_dispatch_payload_separates_exec_and_send(tmp_path):
    from hermes_cli.loops import dispatch_payload

    start = dispatch_payload("start global-test", cwd=tmp_path, session_id="s1", title="T")
    assert start["type"] == "exec"
    assert "Loop: global-test" in start["output"]

    plan = dispatch_payload("plan global-test", cwd=tmp_path, session_id="s1", title="T")
    assert plan["type"] == "send"
    assert "Loop command: plan" in plan["message"]
