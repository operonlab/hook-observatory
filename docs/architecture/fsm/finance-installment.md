# finance.Installment Lifecycle

**Module**: finance | **Entity**: Installment | **States**: 3 | **Transitions**: 2

**Initial**: `active` | **Final**: `completed`, `cancelled`

**All states**: `active`, `completed`, `cancelled`

## State Diagram

```mermaid
stateDiagram-v2
    [*] --> active
    active --> completed : complete
    active --> cancelled : cancel
    completed --> [*]
    cancelled --> [*]
```

## Transition Table

| Source | Target | Event |
|--------|--------|-------|
| active | completed | complete |
| active | cancelled | cancel |
