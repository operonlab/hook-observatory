# finance.Subscription Lifecycle

**Module**: finance | **Entity**: Subscription | **States**: 3 | **Transitions**: 4

**Initial**: `active` | **Final**: `cancelled`

**All states**: `active`, `paused`, `cancelled`

## State Diagram

```mermaid
stateDiagram-v2
    [*] --> active
    active --> paused : pause
    paused --> active : resume
    active --> cancelled : cancel
    paused --> cancelled : cancel
    cancelled --> [*]
```

## Transition Table

| Source | Target | Event |
|--------|--------|-------|
| active | paused | pause |
| paused | active | resume |
| active | cancelled | cancel |
| paused | cancelled | cancel |
