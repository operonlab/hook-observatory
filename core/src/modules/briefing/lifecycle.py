"""Briefing FSM lifecycles — state machines for briefings and entries.

BriefingLifecycle: searching -> analyzing -> debating -> synthesizing -> completed
                   any non-final -> failed

EntryPhase: raw -> analysis -> debate -> conclusion (linear pipeline)
"""

from statemachine import State, StateMachine


class BriefingLifecycle(StateMachine):
    """Main briefing report lifecycle."""

    searching = State(initial=True)
    analyzing = State()
    debating = State()
    synthesizing = State()
    completed = State(final=True)
    failed = State(final=True)

    # Forward pipeline
    start_analyzing = searching.to(analyzing)
    start_debating = analyzing.to(debating)
    start_synthesizing = debating.to(synthesizing)
    complete = synthesizing.to(completed)

    # Failure from any non-final state
    fail = (
        searching.to(failed) | analyzing.to(failed) | debating.to(failed) | synthesizing.to(failed)
    )


class EntryPhase(StateMachine):
    """Entry analysis phase — linear pipeline, no skipping."""

    raw = State(initial=True)
    analysis = State()
    debate = State()
    conclusion = State(final=True)

    analyze = raw.to(analysis)
    start_debate = analysis.to(debate)
    conclude = debate.to(conclusion)
