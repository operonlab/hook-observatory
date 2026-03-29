# Skill Evolution Directions

## Current Focus
- Pursue conciseness: if removing a section maintains output quality, remove it (Karpathy principle)
- Reduce token consumption without degrading quality
- Each mutation round targets one aspect only — no mixed changes
- Prefer explicit instructions over verbose explanations

## Pinned Skills (highest priority)
- message-polish
- content-writer
- smart-search

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
- NEVER remove functional content: tool integrations, search routes, API endpoints,
  external service references (Playwright, Perplexity, MCP tools), workflow branches,
  or fallback paths — these are capabilities, not decoration
- Only remove: redundant prose, verbose explanations, comparison tables, "Agent
  Delegation" sections that add no value

## Lessons Learned (2026-03-30)
- simplify theme deleted Perplexity + Playwright routes from smart-search — tools
  list shrank from 11 to 7 entries, losing real functionality
- Root cause: golden cases only tested basic search, not Perplexity-dependent scenarios
- Fix: scorer now has capability guard (tools list must not shrink) + mutator prompt
  explicitly protects functional content
