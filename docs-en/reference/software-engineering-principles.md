---
doc_version: 2
content_hash: 1e1c0845
source_version: 2
translated_at: 2026-02-23
---

Software Engineering Principles & Design Patterns Reference

  I. Five Foundational Principles (SOLID)

  Proposed by Robert C. Martin (Uncle Bob), the core of object-oriented design:

  Principle: S — Single Responsibility
  Full Name: Single Responsibility (SRP)
  One-liner: A class does one thing and has only one reason to change
  Workshop Example: finance-svc handles only finance, never touches auth
  ────────────────────────────────────────
  Principle: O — Open/Closed
  Full Name: Open/Closed (OCP)
  One-liner: Open for extension, closed for modification (add features without changing existing code)
  Workshop Example: Plugin architecture: add new Plugins without modifying Core
  ────────────────────────────────────────
  Principle: L — Liskov Substitution
  Full Name: Liskov Substitution (LSP)
  One-liner: Subclasses can fully replace parent classes
  Workshop Example: All MCP servers follow the same protocol
  ────────────────────────────────────────
  Principle: I — Interface Segregation
  Full Name: Interface Segregation (ISP)
  One-liner: Don't force implementation of unused interfaces
  Workshop Example: Don't make media-mcp implement finance interfaces
  ────────────────────────────────────────
  Principle: D — Dependency Inversion
  Full Name: Dependency Inversion (DIP)
  One-liner: High-level modules don't depend on low-level ones — both depend on abstractions
  Workshop Example: Service depends on Repository interface, not directly on PostgreSQL

  ---
  II. General Development Principles

  Principle: DRY
  Full Name: Don't Repeat Yourself
  One-liner: Write the same logic only once — extract when repeated
  ────────────────────────────────────────
  Principle: KISS
  Full Name: Keep It Simple, Stupid
  One-liner: If it can be simple, don't make it complex
  ────────────────────────────────────────
  Principle: YAGNI
  Full Name: You Aren't Gonna Need It
  One-liner: Don't build for "might need someday"
  ────────────────────────────────────────
  Principle: SSOT
  Full Name: Single Source of Truth
  One-liner: Every piece of data has exactly one authoritative source
  ────────────────────────────────────────
  Principle: MVP
  Full Name: Minimum Viable Product
  One-liner: The smallest version that can validate the hypothesis
  ────────────────────────────────────────
  Principle: WET
  Full Name: Write Everything Twice
  One-liner: The antithesis of DRY — sometimes duplication is better than wrong abstraction (Rule of Three: abstract on the third)
  ────────────────────────────────────────
  Principle: LoD
  Full Name: Law of Demeter (Principle of Least Knowledge)
  One-liner: Only talk to direct friends — avoid chained calls like a.b.c.d()
  ────────────────────────────────────────
  Principle: CoC
  Full Name: Convention over Configuration
  One-liner: Follow framework conventions, write less config
  ────────────────────────────────────────
  Principle: SoC
  Full Name: Separation of Concerns
  One-liner: Different responsibilities don't mix together
  ────────────────────────────────────────
  Principle: PIE
  Full Name: Program to an Interface, not an Implementation
  One-liner: Code against interfaces to reduce coupling
  ────────────────────────────────────────
