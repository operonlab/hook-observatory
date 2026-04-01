# Automation Boundaries

## Philosophy
Knowing what NOT to automate is as important as knowing what to automate.
When in doubt, default to human review over silent automation.

## Never Automate (Hard Boundaries)

| Category | Examples | Reason |
|----------|----------|--------|
| Security credentials | API key rotation, credential management, secret storage | Irreversible; requires human judgment |
| Financial transactions | Money transfers, payment processing, billing mutations | Legal liability; no auto-rollback |
| Data deletion | Purging user data, dropping schemas, bulk hard-deletes | Irreversible by definition |
| External communications | Sending emails to real recipients, social media posts | Visible to others; reputation risk |
| Production deployments | Pushing to prod, DNS changes, infra teardown | Blast radius too high |
| Access control changes | Granting/revoking permissions, role assignments | Security implications; audit trail required |

## Automate with Confidence Gate (Soft Boundaries)

| Category | Gate | Action if Low Confidence |
|----------|------|--------------------------|
| Capture enrichment | LLM confidence < 0.5 | Flag for human review, do not persist |
| Content classification | Ambiguous or multi-label input | Queue for review; never guess silently |
| Cross-module data sync | Schema mismatch or missing FK | Log warning, skip record, alert |
| Scheduled batch jobs | Error rate > 10% in a single run | Halt job, send alert, do not retry blindly |
| Automated tagging / linking | Similarity score < threshold | Store candidate, require confirmation |

## Always Automate (Green Zone)

- Formatting, linting, type checking (ruff, biome)
- Test execution and CI pipelines
- Log aggregation and monitoring
- Backup and snapshot creation (read-only side effects)
- Schema and Pydantic validation
- Health checks and status reporting
- Cache invalidation on known write paths

## Decision Framework

When unsure whether to automate, ask in order:

1. **Reversible?** No → do not automate (or add explicit confirmation gate)
2. **Affects others?** Yes → do not automate (or add approval step)
3. **Cost of error > cost of manual work?** Yes → do not automate
4. **Can failure be detected automatically?** No → do not automate

All four questions must pass before full automation is acceptable.
