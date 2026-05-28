"""Helpers for the global /view command.

/view is intentionally a send-style command: it does not render project state
itself, because the useful view needs the active agent's tools/context. These
helpers build a regular user prompt that the CLI/gateway can route through the
normal agent path without recursively looking like another slash command.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectViewContext:
    """Runtime hints attached to a /view request."""

    cwd: str = ""
    session_id: str = ""
    title: str = ""
    source: str = ""


def build_project_view_prompt(topic: str = "", *, context: ProjectViewContext | None = None) -> str:
    """Return the agent prompt for a project view.

    The returned text must never start with a slash. Some surfaces dispatch any
    leading slash back through command routing; starting with normal prose keeps
    /view a one-shot prompt instead of a recursive command.
    """
    ctx = context or ProjectViewContext()
    topic = (topic or "").strip()

    target = topic or "the active project/session"
    hints: list[str] = []
    if ctx.cwd:
        hints.append(f"cwd: {ctx.cwd}")
    if ctx.session_id:
        hints.append(f"session: {ctx.session_id}")
    if ctx.title:
        hints.append(f"title: {ctx.title}")
    if ctx.source:
        hints.append(f"source: {ctx.source}")
    hint_block = "\n".join(f"- {hint}" for hint in hints) or "- No runtime hints available."

    return f"""Produce a Project View for {target}.

Runtime hints:
{hint_block}

Ground it before answering: inspect active project files if available (docs/plans, .hermes/loops, status artifacts), git status/latest commit for repo work, and current session context. Do not invent progress; mark unchecked/inferred if needed.

Use this exact shape:
## Project View — <name>

### Aim
- One sentence.

### Checked off
- [x] <verified completed item>

### Current state
- <1-3 bullets>

### Next steps
- [ ] **1. <next concrete step>** — short note.
- [ ] **2. <following step>** — short note.

### Execution mode
- Mode: direct / background / kanban / triage.
- Roles: Manager / Builder / Reviewer / Specialist / Approver, when relevant.

### Blocked / unclear
- None, or the real blocker.

### Best next move
- One concrete action.

### Recommended push
- State whether to do step 1 only, steps 1-3, or the full checklist before pausing.
""".strip()
