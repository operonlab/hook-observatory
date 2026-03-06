# Workshop FSM Registry

Auto-generated overview of all 9 FSM lifecycles (38 states, 42 transitions).

| Module | Entity | States | Transitions | Initial | Final |
|--------|--------|--------|-------------|---------|-------|
| auth | User | 4 | 6 | pending | banned |
| briefing | Briefing | 6 | 8 | searching | completed, failed |
| briefing | Entry | 4 | 3 | raw | conclusion |
| nodeflow | Flow | 4 | 5 | draft | archived |
| nodeflow | FlowRun | 5 | 5 | pending | completed, failed, cancelled |
| nodeflow | NodeRun | 5 | 4 | pending | completed, failed, skipped |
| finance | Transaction | 4 | 5 | pending | completed, cancelled |
| finance | Subscription | 3 | 4 | active | cancelled |
| finance | Installment | 3 | 2 | active | completed, cancelled |

## Individual Diagrams

- [auth.User](auth-user.md)
- [briefing.Briefing](briefing-briefing.md)
- [briefing.Entry](briefing-entry.md)
- [nodeflow.Flow](nodeflow-flow.md)
- [nodeflow.FlowRun](nodeflow-flowrun.md)
- [nodeflow.NodeRun](nodeflow-noderun.md)
- [finance.Transaction](finance-transaction.md)
- [finance.Subscription](finance-subscription.md)
- [finance.Installment](finance-installment.md)
