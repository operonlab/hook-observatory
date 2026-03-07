"""Taskflow FSM lifecycle — state machine for Task status.

    from src.shared.fsm import validate_transition
    from src.modules.taskflow.lifecycle import TaskLifecycle

    validate_transition(TaskLifecycle, old_status, new_status, "task")

Status flow::

              +----------------------------+
              |                            |
    [todo] -> [in_progress] -> [review] -> [done]
                  |                |
                  +-> [blocked]    |
                  |       |        |
                  |       +--------+ (unblock -> review or in_progress)
                  |
                  +-> [cancelled]
"""

from statemachine import State, StateMachine

from src.shared.fsm import register_fsm


class TaskLifecycle(StateMachine):
    """Task status: todo | in_progress | review | done | blocked | cancelled."""

    # States
    todo = State("Todo", initial=True)
    in_progress = State("In Progress")
    review = State("Review")
    done = State("Done", final=True)
    blocked = State("Blocked")
    cancelled = State("Cancelled", final=True)

    # Transitions
    start = todo.to(in_progress)
    submit_review = in_progress.to(review)
    approve = review.to(done)
    block = in_progress.to(blocked) | review.to(blocked)
    unblock_to_progress = blocked.to(in_progress)
    unblock_to_review = blocked.to(review)
    cancel = (
        todo.to(cancelled)
        | in_progress.to(cancelled)
        | review.to(cancelled)
        | blocked.to(cancelled)
    )


register_fsm("taskflow.task", TaskLifecycle)
