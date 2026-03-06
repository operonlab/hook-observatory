#!/usr/bin/env python3
"""Generate Mermaid state diagrams for all Workshop FSMs.

Reads each StateMachine subclass, extracts states and transitions,
and writes Mermaid stateDiagram-v2 markdown files to docs/architecture/fsm/.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

# Add core/src to path so statemachine and shared.fsm resolve
CORE_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(CORE_SRC))

from statemachine import StateMachine


def _load_lifecycle(module_path: Path, mod_name: str) -> ModuleType:
    """Load a lifecycle.py file directly, bypassing package __init__.py.

    This avoids triggering heavy imports (SQLAlchemy models, FastAPI routes)
    that happen when a module's __init__.py is evaluated.
    """
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load all lifecycle modules directly from their file paths
_auth = _load_lifecycle(CORE_SRC / "modules" / "auth" / "lifecycle.py", "_fsm.auth")
_briefing = _load_lifecycle(CORE_SRC / "modules" / "briefing" / "lifecycle.py", "_fsm.briefing")
_nodeflow = _load_lifecycle(CORE_SRC / "modules" / "nodeflow" / "lifecycle.py", "_fsm.nodeflow")
_finance = _load_lifecycle(CORE_SRC / "modules" / "finance" / "lifecycle.py", "_fsm.finance")

UserLifecycle = _auth.UserLifecycle
BriefingLifecycle = _briefing.BriefingLifecycle
EntryPhase = _briefing.EntryPhase
FlowLifecycle = _nodeflow.FlowLifecycle
FlowRunLifecycle = _nodeflow.FlowRunLifecycle
NodeRunLifecycle = _nodeflow.NodeRunLifecycle
TransactionLifecycle = _finance.TransactionLifecycle
SubscriptionLifecycle = _finance.SubscriptionLifecycle
InstallmentLifecycle = _finance.InstallmentLifecycle

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "architecture" / "fsm"


@dataclass
class FsmEntry:
    module: str
    entity: str
    cls: type[StateMachine]


FSM_REGISTRY: list[FsmEntry] = [
    FsmEntry("auth", "User", UserLifecycle),
    FsmEntry("briefing", "Briefing", BriefingLifecycle),
    FsmEntry("briefing", "Entry", EntryPhase),
    FsmEntry("nodeflow", "Flow", FlowLifecycle),
    FsmEntry("nodeflow", "FlowRun", FlowRunLifecycle),
    FsmEntry("nodeflow", "NodeRun", NodeRunLifecycle),
    FsmEntry("finance", "Transaction", TransactionLifecycle),
    FsmEntry("finance", "Subscription", SubscriptionLifecycle),
    FsmEntry("finance", "Installment", InstallmentLifecycle),
]


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


@dataclass
class FsmAnalysis:
    module: str
    entity: str
    states: list[str]
    initial_states: list[str]
    final_states: list[str]
    transitions: list[tuple[str, str, str]]  # (source, target, event_name)

    @property
    def state_count(self) -> int:
        return len(self.states)

    @property
    def transition_count(self) -> int:
        return len(self.transitions)


def analyze_fsm(entry: FsmEntry) -> FsmAnalysis:
    """Extract full FSM metadata from a StateMachine class."""
    cls = entry.cls

    states = [s.id for s in cls.states]
    initial_states = [s.id for s in cls.states if s.initial]
    final_states = [s.id for s in cls.states if s.final]

    transitions: list[tuple[str, str, str]] = []
    for event in cls.events:
        for t in event._transitions:
            transitions.append((t.source.id, t.target.id, event.id))

    return FsmAnalysis(
        module=entry.module,
        entity=entry.entity,
        states=states,
        initial_states=initial_states,
        final_states=final_states,
        transitions=transitions,
    )


# ---------------------------------------------------------------------------
# Mermaid generation
# ---------------------------------------------------------------------------


def generate_mermaid(analysis: FsmAnalysis) -> str:
    """Generate a Mermaid stateDiagram-v2 string."""
    lines = ["stateDiagram-v2"]

    # Initial state arrows
    for s in analysis.initial_states:
        lines.append(f"    [*] --> {s}")

    # Transition arrows
    for source, target, event_name in analysis.transitions:
        lines.append(f"    {source} --> {target} : {event_name}")

    # Final state arrows
    for s in analysis.final_states:
        lines.append(f"    {s} --> [*]")

    return "\n".join(lines)


def generate_transition_table(analysis: FsmAnalysis) -> str:
    """Generate a markdown transition table."""
    lines = [
        "| Source | Target | Event |",
        "|--------|--------|-------|",
    ]
    for source, target, event_name in analysis.transitions:
        lines.append(f"| {source} | {target} | {event_name} |")
    return "\n".join(lines)


def generate_file_content(analysis: FsmAnalysis) -> str:
    """Generate the full markdown file for one FSM."""
    mermaid = generate_mermaid(analysis)
    table = generate_transition_table(analysis)

    initial_str = ", ".join(f"`{s}`" for s in analysis.initial_states)
    final_str = ", ".join(f"`{s}`" for s in analysis.final_states) or "none"
    all_states_str = ", ".join(f"`{s}`" for s in analysis.states)

    return f"""# {analysis.module}.{analysis.entity} Lifecycle

**Module**: {analysis.module} | **Entity**: {analysis.entity} | **States**: {analysis.state_count} | **Transitions**: {analysis.transition_count}

**Initial**: {initial_str} | **Final**: {final_str}

**All states**: {all_states_str}

## State Diagram

```mermaid
{mermaid}
```

## Transition Table

{table}
"""


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------


def generate_readme(analyses: list[FsmAnalysis]) -> str:
    """Generate the summary README.md."""
    total_states = sum(a.state_count for a in analyses)
    total_transitions = sum(a.transition_count for a in analyses)

    lines = [
        "# Workshop FSM Registry",
        "",
        f"Auto-generated overview of all {len(analyses)} FSM lifecycles "
        f"({total_states} states, {total_transitions} transitions).",
        "",
        "| Module | Entity | States | Transitions | Initial | Final |",
        "|--------|--------|--------|-------------|---------|-------|",
    ]

    for a in analyses:
        initial = ", ".join(a.initial_states)
        final = ", ".join(a.final_states) or "-"
        lines.append(
            f"| {a.module} | {a.entity} | {a.state_count} | "
            f"{a.transition_count} | {initial} | {final} |"
        )

    lines.append("")
    lines.append("## Individual Diagrams")
    lines.append("")
    for a in analyses:
        filename = f"{a.module}-{a.entity.lower()}.md"
        lines.append(f"- [{a.module}.{a.entity}]({filename})")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    analyses: list[FsmAnalysis] = []
    for entry in FSM_REGISTRY:
        analysis = analyze_fsm(entry)
        analyses.append(analysis)

        filename = f"{analysis.module}-{analysis.entity.lower()}.md"
        filepath = OUTPUT_DIR / filename
        filepath.write_text(generate_file_content(analysis))
        print(f"  Generated: {filepath.relative_to(REPO_ROOT)}")

    # README
    readme_path = OUTPUT_DIR / "README.md"
    readme_path.write_text(generate_readme(analyses))
    print(f"  Generated: {readme_path.relative_to(REPO_ROOT)}")

    # Summary
    total_states = sum(a.state_count for a in analyses)
    total_transitions = sum(a.transition_count for a in analyses)
    print(f"\nTotal: {len(analyses)} FSMs, {total_states} states, {total_transitions} transitions")


if __name__ == "__main__":
    main()
