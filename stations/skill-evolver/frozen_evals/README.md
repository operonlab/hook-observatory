# Frozen Evaluations

These files define the scoring criteria for skill evolution. They are **intentionally frozen** — the mutation engine (mutator.py) must never modify them.

## Why frozen?

This is the Karpathy AutoResearch principle: if the agent can modify both the optimized code AND the evaluation criteria, it will game the metrics instead of genuinely improving.

The evaluation function must be:
1. Written by a human
2. Reviewed before activation
3. Never modified by automated evolution runs
4. Only updated through explicit human commits

## Files

- `quality_judge.txt` — System prompt for LLM-as-Judge quality scoring
- `scoring_rubric.json` — Dimension weights and thresholds

## Updating

To update these files:
1. Create a new git branch (not the auto-evolve branch)
2. Modify the file
3. Run a baseline comparison to verify the new criteria
4. Commit with clear rationale
