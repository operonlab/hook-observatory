---
doc_version: 1
content_hash: bbc48960
source_version: 1
translated_at: 2026-02-23
---

# Feature Lifecycle: POC → Production

## Decision Tree

```
New idea arrives
    │
    ├─ Uncertain / Verification needed → lab/<name>-poc/
    │
    └─ Decision made / Clear specifications → Directly to services/<name>/
```

## Phases

### Phase 1: Explore (lab/)

```
lab/<name>-poc/
├── README.md      ← Write down: Goals, Hypotheses, Success Criteria
├── outputs/       ← Skill output .md / .json
└── scripts/       ← Fast verification scripts
```

- Skill output path: `~/workshop/lab/<name>-poc/outputs/`
- Format: .md (Easy to read, fast iteration)
- No need for pyproject.toml, no need for tests/, no need to follow formal structure
- README.md continuously updated with observations and findings

### Phase 2: Validate

- Evaluate POC results based on success criteria
- Record conclusions in README.md

**If it fails**:
```
lab/<name>-poc/README.md  ← Add "Why it failed" and "Lessons learned"
lab/<name>-poc/outputs/   ← Delete (or retain valuable ones)
```
Failure records are valuable — avoid repeating the same mistakes in the future.

### Phase 3: Graduate 🎓

**If successful → Formalize**:

1. Build formal service scaffold:
   ```bash
   mkdir -p services/<name>/{src/<name>/{routes,models,core},tests,migrations}
   ```

2. Build formal frontend (if needed):
   ```bash
   mkdir -p apps/<name>/{src/{components,pages,hooks},public}
   ```

3. Write migration scripts (.md → DB):
   ```
   lab/<name>-poc/scripts/migrate-to-db.py
   ```

4. Import data and verify

5. Update lab README.md:
   ```markdown
   ## Status: GRADUATED
   Migrated to services/<name>/ + apps/<name>/ on YYYY-MM-DD
   ```

### Phase 4: Cleanup

| Status | Action |
|------|------|
| Graduated | Keep README.md, delete outputs/ |
| Failed | Keep README.md, delete the rest |
| Idle > 30 days | Remind to decide: Keep or Cleanup |

## Skill Output Path Convention

| Phase | Output Path | Format |
|------|---------|------|
| POC | `~/workshop/lab/<name>-poc/outputs/` | .md / .json |
| Production | HTTP API → PostgreSQL | DB records |

## Rules

1. `services/` and `apps/` **will absolutely not have .md artifacts** — code only
2. Content in `lab/` **will not be** imported by any formal service
3. Every POC has a README.md — documented even if it fails
4. POC naming: `<domain>-poc` (distinguished from formal names in services/ with a suffix)
