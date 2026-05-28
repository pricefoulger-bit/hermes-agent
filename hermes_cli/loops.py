"""Repo-local Fruit-Loop controller state for slash surfaces.

This intentionally mirrors the V1 TUI service: local files first, no hidden
workers, and lifecycle/status commands handled without submitting back to the
model.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

LoopPhase = Literal["planning", "executing", "blocked", "closing", "closed"]
DEFAULT_SLUG = "fruit-loop"
LOCAL_COMMANDS = {"start", "status", "complete", "block", "close"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64]
    return out or DEFAULT_SLUG


def split(arg: str) -> list[str]:
    return [part for part in arg.strip().split() if part]


def loop_command(arg: str) -> str:
    cmd = split(arg)[0] if split(arg) else "start"
    return cmd if cmd in {"start", "status", "docs", "grill", "plan", "run", "complete", "block", "close"} else "start"


@dataclass
class ParsedLoopArgs:
    command: str
    slug: str
    docs_hint: str
    raw: str
    run_next: bool
    story: str
    note: str


def parse_loop_args(arg: str) -> ParsedLoopArgs:
    parts = split(arg)
    command = loop_command(arg)
    explicit = bool(parts and parts[0] == command)
    maybe = parts[1] if explicit and len(parts) > 1 else (parts[0] if parts else "")
    run_next = command == "run" and maybe == "next"
    maybe_slug = parts[2] if run_next and len(parts) > 2 else maybe
    rest_start = 3 if explicit and run_next else (2 if explicit else 1)
    rest = parts[rest_start:]
    story = parts[2] if command in {"complete", "block"} and len(parts) > 2 else ""
    if command in {"complete", "block"}:
        note = " ".join(parts[3:])
    elif command == "close":
        note = " ".join(rest)
    else:
        note = ""
    return ParsedLoopArgs(
        command=command,
        slug=slugify(maybe_slug or DEFAULT_SLUG),
        docs_hint=" ".join(rest) if command == "start" else "",
        raw=arg.strip(),
        run_next=run_next,
        story=story,
        note=note,
    )


def loop_state_dir(cwd: str | Path, slug: str) -> Path:
    return Path(cwd or os.getcwd()) / ".hermes" / "loops" / slug


def _state_file(root: Path) -> Path:
    return root / "loop.json"


def _stories_file(root: Path) -> Path:
    return root / "stories.json"


def _status_file(root: Path) -> Path:
    return root / "status.md"


def _progress_file(root: Path) -> Path:
    return root / "progress.md"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_stories(root: Path) -> list[dict[str, Any]]:
    raw = _read_json(_stories_file(root), [])
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("stories"), list):
        return [x for x in raw["stories"] if isinstance(x, dict)]
    return []


def _write_stories(root: Path, stories: list[dict[str, Any]]) -> None:
    _stories_file(root).write_text(json.dumps(stories, indent=2) + "\n", encoding="utf-8")


def _is_done(story: dict[str, Any]) -> bool:
    return str(story.get("status") or "").lower() in {"done", "complete", "completed"}


def _is_running(story: dict[str, Any]) -> bool:
    return str(story.get("status") or "").lower() in {"running", "in_progress"}


def _is_blocked(story: dict[str, Any]) -> bool:
    return str(story.get("status") or "").lower() == "blocked"


def _is_todo(story: dict[str, Any]) -> bool:
    status = str(story.get("status") or "").lower()
    return not status or status in {"todo", "queued", "ready"}


def _counts(stories: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "done": sum(1 for s in stories if _is_done(s)),
        "running": sum(1 for s in stories if _is_running(s)),
        "queued": sum(1 for s in stories if _is_todo(s)),
        "blocked": sum(1 for s in stories if _is_blocked(s)),
    }


def _next_line(state: dict[str, Any]) -> str:
    stories = state.get("stories") or {}
    if state.get("status") == "executing":
        return f"Next: complete or block the running story for {state.get('slug', DEFAULT_SLUG)}"
    if state.get("status") == "blocked":
        return f"Next: resolve blocker or /loop block {state.get('slug', DEFAULT_SLUG)} <story> <reason>"
    if state.get("status") == "closing" or (
        stories.get("done", 0) > 0
        and stories.get("queued", 0) == 0
        and stories.get("running", 0) == 0
        and stories.get("blocked", 0) == 0
    ):
        return f"Next: /loop close {state.get('slug', DEFAULT_SLUG)}"
    if stories.get("queued", 0) > 0:
        return f"Next: /loop run next {state.get('slug', DEFAULT_SLUG)}"
    if state.get("docs_hint"):
        return f"Next: /loop docs {state.get('slug', DEFAULT_SLUG)}"
    return f"Next: /loop docs {state.get('slug', DEFAULT_SLUG)} <path-or-url>"


def _render_status(state: dict[str, Any], root: Path, just_started: bool = False, note: str = "") -> str:
    lines = [
        f"Loop: {state.get('slug', DEFAULT_SLUG)}",
        f"Phase: {state.get('status', 'planning')}",
    ]
    if just_started:
        lines.append("Status: started")
    lines.extend(
        [
            f"Docs: {state.get('docs_hint') or 'none yet'}",
            "Stories: "
            f"{state.get('stories', {}).get('done', 0)} done / "
            f"{state.get('stories', {}).get('running', 0)} running / "
            f"{state.get('stories', {}).get('queued', 0)} queued / "
            f"{state.get('stories', {}).get('blocked', 0)} blocked",
        ]
    )
    if note:
        lines.extend(["", note])
    lines.extend(["", f"State: {root}", f"Session: {state.get('session_id') or 'unknown'}", f"Title: {state.get('title') or '—'}", "", _next_line(state)])
    return "\n".join(lines)


def _seed(root: Path) -> None:
    for name in ("runs", "reviews", "archive"):
        (root / name).mkdir(parents=True, exist_ok=True)
    defaults = {
        "docs.md": "# Docs\n\nSources: none yet\n",
        "decisions.md": "# Decisions\n\n## Confirmed\n\n## Inferred\n\n## Deferred\n",
        "prd.md": "# PRD\n\nOutcome: TBD\n",
        "stories.json": "[]\n",
        "progress.md": "# Progress\n\n## Codebase Patterns\n\n## Log\n",
    }
    for name, content in defaults.items():
        path = root / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def _save_state(root: Path, state: dict[str, Any], note: str = "") -> None:
    _state_file(root).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    _status_file(root).write_text(_render_status(state, root, False, note) + "\n", encoding="utf-8")


def start_loop(arg: str, *, cwd: str | Path, session_id: str = "unknown", title: str = "") -> str:
    parsed = parse_loop_args(arg)
    root = loop_state_dir(cwd, parsed.slug)
    now = _now()
    prior = _read_json(_state_file(root), {}) if _state_file(root).exists() else {}
    stories = _read_stories(root) if root.exists() else []
    root.mkdir(parents=True, exist_ok=True)
    _seed(root)
    state = {
        "slug": parsed.slug,
        "title": title or prior.get("title") or Path(cwd).name or parsed.slug,
        "status": prior.get("status") or "planning",
        "docs_hint": parsed.docs_hint or prior.get("docs_hint") or "",
        "session_id": session_id or prior.get("session_id") or "unknown",
        "cwd": str(cwd),
        "created_at": prior.get("created_at") or now,
        "updated_at": now,
        "stories": prior.get("stories") or _counts(stories),
    }
    _state_file(root).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    text = _render_status(state, root, True)
    _status_file(root).write_text(text + "\n", encoding="utf-8")
    return text


def status_loop(slug: str, cwd: str | Path) -> str:
    root = loop_state_dir(cwd, slug)
    if not _state_file(root).exists():
        return "\n".join([
            f"Loop: {slug}",
            "Phase: not started",
            "Docs: none yet",
            "Stories: 0 done / 0 running / 0 queued / 0 blocked",
            "",
            f"State: {root}",
            "Next: /loop start <name> <docs-or-goal>",
        ])
    state = _read_json(_state_file(root), {})
    state["stories"] = _counts(_read_stories(root))
    state["updated_at"] = _now()
    _save_state(root, state)
    return _render_status(state, root)


def _git(cwd: str | Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True, stderr=subprocess.DEVNULL).strip()


def _detect_commands(cwd: str | Path) -> list[str]:
    cwd_path = Path(cwd)
    commands: list[str] = []
    pkg = cwd_path / "package.json"
    if pkg.exists():
        data = _read_json(pkg, {})
        scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        if scripts.get("test"):
            commands.append("bun test")
        if scripts.get("build"):
            commands.append("bun run build")
        if (cwd_path / "tsconfig.json").exists():
            commands.append("bunx tsc --noEmit")
    return commands


def _runnable(stories: list[dict[str, Any]]) -> dict[str, Any] | None:
    done = {s.get("id") for s in stories if _is_done(s) and isinstance(s.get("id"), str)}
    for story in stories:
        deps = story.get("depends_on") or []
        if _is_todo(story) and all(dep in done for dep in deps):
            return story
    return None


def _preflight(cwd: str | Path, root: Path, story: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    required: list[str] = []
    warnings: list[str] = []
    if not _state_file(root).exists():
        required.append("loop state missing")
    if not _stories_file(root).exists():
        required.append("stories.json missing")
    try:
        _git(cwd, ["rev-parse", "--is-inside-work-tree"])
    except Exception:
        required.append("not inside a git worktree")
    try:
        if _git(cwd, ["status", "--porcelain"]):
            warnings.append("working tree has uncommitted changes")
    except Exception:
        pass
    if story is None:
        required.append("no runnable story with dependencies satisfied")
    ui_text = f"{(story or {}).get('kind', '')} {(story or {}).get('title', '')} {(story or {}).get('objective', '')}".lower()
    if re.search(r"\b(ui|browser|visual|screen|click)\b", ui_text) and not os.getenv("HERMES_BROWSER_TOOL"):
        required.append("UI/browser story requires browser verification tool availability")
    return required, warnings, _detect_commands(cwd)


def _append_progress(root: Path, line: str) -> None:
    fallback = "# Progress\n\n## Codebase Patterns\n\n## Log\n"
    base = _progress_file(root).read_text(encoding="utf-8") if _progress_file(root).exists() else fallback
    _progress_file(root).write_text(f"{base.rstrip()}\n- {_now()} — {line}\n", encoding="utf-8")


def run_loop(slug: str, cwd: str | Path) -> str:
    root = loop_state_dir(cwd, slug)
    if not _state_file(root).exists():
        return status_loop(slug, cwd)
    state = _read_json(_state_file(root), {})
    if state.get("status") == "closed":
        return _render_status(state, root, False, "Blocked: loop is closed")
    stories = _read_stories(root)
    story = _runnable(stories)
    required, warnings, commands = _preflight(cwd, root, story)
    if required:
        state.update({"status": "blocked", "stories": _counts(stories), "updated_at": _now()})
        note = "\n".join(["Blocked: preflight failed", *[f"- required: {x}" for x in required], *[f"- warning: {x}" for x in warnings]])
        _save_state(root, state, note)
        return _render_status(state, root, False, note)
    assert story is not None
    idx = stories.index(story)
    stories[idx] = {**story, "status": "running"}
    _write_stories(root, stories)
    state.update({"status": "executing", "stories": _counts(stories), "updated_at": _now()})
    _save_state(root, state, "\n".join([f"Warning: {x}" for x in warnings]))
    _append_progress(root, f"started {story.get('id') or 'story'}: {story.get('title') or story.get('objective') or 'untitled'}")
    verification = story.get("verification") or commands
    return "\n".join([
        f"Run: {story.get('id') or 'story'} — {story.get('title') or 'Untitled'}",
        f"Loop: {slug}",
        f"State: {root}",
        "",
        "Preflight: passed",
        *[f"Warning: {x}" for x in warnings],
        f"Verification commands detected: {'; '.join(commands) if commands else 'none'}",
        "",
        "Story objective:",
        str(story.get("objective") or "No objective set."),
        "",
        "Acceptance:",
        *([f"- {x}" for x in story.get("acceptance", [])] if story.get("acceptance") else ["- Not specified"]),
        "",
        "Allowed paths:",
        *([f"- {x}" for x in story.get("allowed_paths", [])] if story.get("allowed_paths") else ["- Not specified"]),
        "",
        "Verification:",
        *([f"- {x}" for x in verification] if verification else []),
        "",
        "Do this one foreground story now. Do not auto-retry on failure; verify or block with the exact reason.",
    ])


def transition_loop(slug: str, cwd: str | Path, story_id: str, note: str, status: Literal["done", "blocked"]) -> str:
    root = loop_state_dir(cwd, slug)
    if not _state_file(root).exists():
        return status_loop(slug, cwd)
    state = _read_json(_state_file(root), {})
    if state.get("status") == "closed":
        return _render_status(state, root, False, "Blocked: loop is closed")
    if not story_id:
        return _render_status(state, root, False, f"Blocked: missing story id for /loop {'complete' if status == 'done' else 'block'}")
    stories = _read_stories(root)
    idx = next((i for i, story in enumerate(stories) if story.get("id") == story_id), -1)
    if idx < 0:
        return _render_status(state, root, False, f"Blocked: story not found: {story_id}")
    at = _now()
    detail = note or ("verified" if status == "done" else "blocked")
    if status == "done":
        stories[idx] = {**stories[idx], "status": "done", "completed_at": at, "completed_note": detail}
    else:
        stories[idx] = {**stories[idx], "status": "blocked", "blocked_at": at, "blocked_reason": detail}
    _write_stories(root, stories)
    c = _counts(stories)
    phase: LoopPhase = "blocked" if status == "blocked" else ("closing" if c["queued"] == 0 and c["running"] == 0 and c["blocked"] == 0 else "planning")
    state.update({"status": phase, "stories": c, "updated_at": at})
    label = f"Completed: {story_id}" if status == "done" else f"Blocked: {story_id}"
    _append_progress(root, f"{'completed' if status == 'done' else 'blocked'} {story_id}: {detail}")
    _save_state(root, state, f"{label}\n{detail}")
    return _render_status(state, root, False, f"{label}\n{detail}")


def close_loop(slug: str, cwd: str | Path, note: str) -> str:
    root = loop_state_dir(cwd, slug)
    if not _state_file(root).exists():
        return status_loop(slug, cwd)
    state = _read_json(_state_file(root), {})
    stories = _read_stories(root)
    at = _now()
    safe_note = note or "closed"
    archive = root / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    closeout = "\n".join([
        f"# Closeout: {slug}",
        "",
        f"Closed: {at}",
        f"Note: {safe_note}",
        "",
        "## Status Snapshot",
        "",
        (_status_file(root).read_text(encoding="utf-8").strip() if _status_file(root).exists() else "No status snapshot."),
        "",
        "## PRD Snapshot",
        "",
        ((root / "prd.md").read_text(encoding="utf-8").strip() if (root / "prd.md").exists() else "No PRD snapshot."),
        "",
        "## Progress Snapshot",
        "",
        (_progress_file(root).read_text(encoding="utf-8").strip() if _progress_file(root).exists() else "No progress snapshot."),
        "",
    ])
    closeout_path = archive / "closeout.md"
    if closeout_path.exists():
        closeout_path = archive / f"closeout-{at.replace(':', '').replace('.', '')}.md"
    closeout_path.write_text(closeout, encoding="utf-8")
    state.update({"status": "closed", "stories": _counts(stories), "updated_at": at})
    _save_state(root, state, f"Status: closed\nCloseout: {safe_note}")
    return _render_status(state, root, False, f"Status: closed\nCloseout: {safe_note}")


def controller_prompt(arg: str, *, cwd: str | Path, session_id: str = "unknown", title: str = "") -> str:
    parsed = parse_loop_args(arg)
    spec = re.sub(r"^\S+\s*", "", parsed.raw).strip()
    return "\n".join([
        "Start or continue a visible Fruit-Loop project controller.",
        "",
        "Use /grill-me-with-docs first when docs or requirements are named. Do not hide this as generic background workers; keep visible foreground progress unless explicit Kanban fan-out is chosen.",
        "",
        f"Loop command: {parsed.command}",
        f"Project/docs hint: {spec or cwd}",
        f"Session: {session_id or 'unknown'}",
        f"Title: {title or '—'}",
        "",
        "Required output shape:",
        "1. PRD — concise aim, users, constraints, non-goals.",
        "2. stories — bite-sized build/review/test slices.",
        "3. Progress surface — where status lives and how Price sees it.",
        "4. Execution — next foreground slice, with no hidden workers unless explicitly approved.",
        "",
        "If starting from docs, read the docs first and grill the plan against them before implementation.",
    ])


def loop_text(arg: str, *, cwd: str | Path | None = None, session_id: str = "unknown", title: str = "") -> str:
    cwd = str(cwd or os.getenv("TERMINAL_CWD") or os.getcwd())
    parsed = parse_loop_args(arg)
    if parsed.command == "start":
        return start_loop(arg, cwd=cwd, session_id=session_id, title=title)
    if parsed.command == "status":
        return status_loop(parsed.slug, cwd)
    if parsed.command == "run" and parsed.run_next:
        return run_loop(parsed.slug, cwd)
    if parsed.command == "complete":
        return transition_loop(parsed.slug, cwd, parsed.story, parsed.note, "done")
    if parsed.command == "block":
        return transition_loop(parsed.slug, cwd, parsed.story, parsed.note, "blocked")
    if parsed.command == "close":
        return close_loop(parsed.slug, cwd, parsed.note)
    return controller_prompt(arg, cwd=cwd, session_id=session_id, title=title)


def dispatch_payload(arg: str, *, cwd: str | Path | None = None, session_id: str = "unknown", title: str = "") -> dict[str, str]:
    parsed = parse_loop_args(arg)
    text = loop_text(arg, cwd=cwd, session_id=session_id, title=title)
    if parsed.command in LOCAL_COMMANDS:
        return {"type": "exec", "output": text}
    if parsed.command == "run" and parsed.run_next:
        return {"type": "send", "message": text}
    return {"type": "send", "message": text}
