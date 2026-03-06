"""Nodeflow FSM -- Flow, FlowRun, and NodeRun lifecycle state machines.

FlowLifecycle:
    draft    (initial) -- Newly created, not yet activated
    active             -- Running and accepting triggers
    paused             -- Temporarily halted
    archived (final)   -- Permanently retired

FlowRunLifecycle:
    pending   (initial) -- Queued for execution
    running             -- Currently executing
    completed (final)   -- Finished successfully
    failed    (final)   -- Finished with error
    cancelled (final)   -- Aborted before completion

NodeRunLifecycle:
    pending   (initial) -- Waiting to execute
    running             -- Currently executing
    completed (final)   -- Finished successfully
    failed    (final)   -- Finished with error
    skipped   (final)   -- Bypassed (unreachable branch)
"""

from statemachine import State, StateMachine

from src.shared.fsm import register_fsm


class FlowLifecycle(StateMachine):
    """Flow status transitions."""

    # States
    draft = State(initial=True)
    active = State()
    paused = State()
    archived = State(final=True)

    # Transitions
    activate = draft.to(active)
    pause = active.to(paused)
    resume = paused.to(active)
    archive = active.to(archived) | paused.to(archived)


class FlowRunLifecycle(StateMachine):
    """FlowRun status transitions."""

    # States
    pending = State(initial=True)
    running = State()
    completed = State(final=True)
    failed = State(final=True)
    cancelled = State(final=True)

    # Transitions
    start = pending.to(running)
    complete = running.to(completed)
    fail = running.to(failed)
    cancel = running.to(cancelled) | pending.to(cancelled)


class NodeRunLifecycle(StateMachine):
    """NodeRun (NodeRunLog) status transitions."""

    # States
    pending = State(initial=True)
    running = State()
    completed = State(final=True)
    failed = State(final=True)
    skipped = State(final=True)

    # Transitions
    start = pending.to(running)
    complete = running.to(completed)
    fail = running.to(failed)
    skip = pending.to(skipped)


register_fsm("nodeflow.flow", FlowLifecycle)
register_fsm("nodeflow.flow_run", FlowRunLifecycle)
register_fsm("nodeflow.node_run", NodeRunLifecycle)
