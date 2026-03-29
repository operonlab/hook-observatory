# Skill Evolution Directions

## Current Focus
- Pursue conciseness: if removing a section maintains output quality, remove it (Karpathy principle)
- Reduce token consumption without degrading quality
- Each mutation round targets one aspect only — no mixed changes
- Prefer explicit instructions over verbose explanations

## Pinned Skills (highest priority)
- message-polish
- content-writer

## Excluded Skills (never evolve)
- envkit, tmux-relay, tmux-expert, session-redactor  # system operations
- brainstorming, divergent-thinking                   # creative, no objective metric
- update-config, create-skill, create-command         # meta-skills
- skill-publish, skill-proxy                          # infrastructure

## Mutation Constraints
- Never alter YAML frontmatter (name, description, version, tools, io)
- Never remove MANDATORY or CRITICAL marked sections
- Never change a skill's fundamental purpose or io schema
- Never introduce new external dependencies
- Preserve all script paths and CLI references
