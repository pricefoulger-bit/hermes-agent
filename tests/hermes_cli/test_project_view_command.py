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


def test_view_command_registered_globally():
    from hermes_cli.commands import resolve_command

    cmd = resolve_command("view")
    assert cmd is not None
    assert cmd.name == "view"
    assert cmd.category == "Session"
    assert "project" in cmd.args_hint


def test_project_view_prompt_shape_does_not_recurse(tmp_path):
    from hermes_cli.project_view import ProjectViewContext, build_project_view_prompt

    prompt = build_project_view_prompt(
        "Hermes UX",
        context=ProjectViewContext(
            cwd=str(tmp_path),
            session_id="sess-test",
            title="UX Work",
            source="cli",
        ),
    )

    assert not prompt.startswith("/")
    assert "Produce a Project View for Hermes UX" in prompt
    assert "cwd:" in prompt
    assert "### Checked off" in prompt
    assert "### Recommended push" in prompt


def test_cli_view_queues_project_view_prompt(tmp_path, monkeypatch):
    cli = _make_cli(tmp_path, monkeypatch)
    printed = []
    monkeypatch.setattr("cli._cprint", lambda text: printed.append(str(text)))

    cli._handle_view_command("/view Hermes UX")

    assert not cli._pending_input.empty()
    queued = cli._pending_input.get_nowait()
    assert queued.startswith("Produce a Project View for Hermes UX")
    assert "source: cli" in queued
    assert printed == ["  Project view queued."]
