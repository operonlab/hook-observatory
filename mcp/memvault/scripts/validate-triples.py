#!/usr/bin/env python3
"""validate-triples.py — Memvault V2 triple validator. Reads JSON from stdin."""

import json
import sys

PREDICATES = {
    "uses", "requires", "depends_on",
    "configured_with", "format_is", "default_is",
    "causes", "prevents", "fixes", "enables",
    "should", "should_NOT",
    "pattern_is", "flow_is", "implemented_as",
    "chosen_over", "reason_for",
    "improves", "degrades", "maps_to",
}
# Gemini sometimes invents predicates — normalize to canonical ones
PREDICATE_ALIASES = {
    "supports": "enables", "promotes": "improves",
    "complements": "enables", "type": "format_is",
    "version": "configured_with", "updated with": "configured_with",
    "replaced_by": "chosen_over", "replaces": "chosen_over",
    "is_a": "maps_to", "has": "configured_with",
    "related_to": "enables", "affects": "causes",
    "blocks": "prevents", "triggers": "causes",
    "extends": "depends_on", "wraps": "implemented_as",
    "needs": "requires", "conflicts_with": "prevents",
    "preferred_over": "chosen_over", "prefers": "should",
    "avoids": "should_NOT", "creates": "enables",
    "generates": "enables", "validates": "fixes",
    "implements": "implemented_as", "contains": "configured_with",
    "provides": "enables", "disables": "prevents",
    "overrides": "configured_with", "inherits": "depends_on",
    "returns": "flow_is", "scans": "uses",
    "suitable_for": "should", "favors": "should",
    "runs": "uses", "invokes": "uses",
    "reads": "uses", "writes": "uses",
    "calls": "uses", "emits": "causes",
    "handles": "flow_is", "parses": "uses",
    "stores": "configured_with", "caches": "configured_with",
    "logs": "uses", "monitors": "uses",
    "connects_to": "depends_on", "listens_on": "configured_with",
    "exposes": "enables", "serves": "enables",
    "integrates_with": "depends_on", "built_with": "uses",
    "optimizes": "improves", "accelerates": "improves",
    "simplifies": "improves", "automates": "enables",
    "ensures": "should", "enforces": "should",
    "retains": "configured_with", "released_with": "configured_with",
    "is": "format_is", "focus": "pattern_is",
    "produces": "causes", "outputs": "causes",
    "converts": "flow_is", "transforms": "flow_is",
    "loads": "uses", "imports": "uses",
    "exports": "enables", "deploys": "uses",
    "configures": "configured_with", "sets": "configured_with",
    "defines": "format_is", "specifies": "format_is",
    "limits": "configured_with", "restricts": "prevents",
    "allows": "enables", "permits": "enables",
    "requires_not": "should_NOT", "must_not": "should_NOT",
    "depends": "depends_on", "relies_on": "depends_on",
    "based_on": "depends_on", "derived_from": "depends_on",
    "replicated_from": "maps_to", "mirrors": "maps_to",
    "equivalent_to": "maps_to", "aliases": "maps_to",
    "solves": "fixes", "resolves": "fixes", "repairs": "fixes",
    "breaks": "degrades", "degrades_to": "degrades",
    "enhances": "improves", "boosts": "improves",
    "reduces": "improves", "minimizes": "improves",
    "includes": "configured_with", "constrained_by": "requires",
    "ignores": "should_NOT", "updated_with": "configured_with",
    "lacks": "should", "missing": "should",
    "conflicts": "prevents", "compatible_with": "enables",
    "incompatible_with": "prevents", "deprecated": "should_NOT",
    "replaces_with": "chosen_over", "migrated_to": "chosen_over",
    "wraps_around": "implemented_as", "abstracts": "implemented_as",
    "delegates_to": "depends_on", "proxies": "depends_on",
    "notifies": "causes", "signals": "causes",
    "listens_to": "depends_on", "watches": "uses",
    "spawns": "causes", "terminates": "prevents",
    "persists": "configured_with", "caches_in": "configured_with",
}
CORRECTION_CATEGORIES = {"tool_behavior", "config", "architecture", "workflow", "preference", "technical", "naming", "syntax", "performance"}
REQUIRED = {"session_id", "timestamp", "topic", "skip", "triples", "corrections", "tags"}


def err(msg):
    print(json.dumps({"valid": False, "error": msg}), file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(f"[warn] {msg}", file=sys.stderr)


def validate(data):
    # skip-only is valid
    if data.get("skip") is True and len(data) == 1:
        return data

    # Required fields
    missing = REQUIRED - set(data)
    if missing:
        err(f"Missing required fields: {sorted(missing)}")

    for field in ("triples", "corrections", "tags"):
        if not isinstance(data[field], list):
            err(f"'{field}' must be a list")

    # Normalize and validate triples
    bad = []
    normalized = 0
    for i, t in enumerate(data["triples"]):
        if not isinstance(t, dict):
            err(f"Triple[{i}] is not an object")
        for k in ("s", "p", "o"):
            if k not in t or not isinstance(t[k], str) or not t[k].strip():
                err(f"Triple[{i}].{k} must be a non-empty string")
        # Normalize aliases before validation
        p = t["p"]
        if p not in PREDICATES and p in PREDICATE_ALIASES:
            t["p"] = PREDICATE_ALIASES[p]
            normalized += 1
        elif p not in PREDICATES and p.lower().replace(" ", "_") in PREDICATE_ALIASES:
            t["p"] = PREDICATE_ALIASES[p.lower().replace(" ", "_")]
            normalized += 1
        if t["p"] not in PREDICATES:
            bad.append(f"Triple[{i}]: '{t['p']}'")
    if bad:
        err(f"Invalid predicate(s): {bad}. Allowed: {sorted(PREDICATES)}")
    if normalized:
        warn(f"Normalized {normalized} predicate(s) via alias mapping")

    # Validate corrections
    for i, c in enumerate(data["corrections"]):
        if not isinstance(c, dict) or not isinstance(c.get("fact", None), str):
            err(f"Correction[{i}] missing or invalid 'fact' field")
        cat = c.get("category", "")
        if cat and cat not in CORRECTION_CATEGORIES:
            err(f"Correction[{i}] invalid category '{cat}'. Allowed: {sorted(CORRECTION_CATEGORIES)}")

    # Soft warnings
    n = len(data["triples"])
    if n == 0:   warn('triples is empty — consider {"skip": true}')
    if n > 12:   warn(f"{n} triples (recommended max: 12)")
    t = len(data["tags"])
    if t < 3:    warn(f"Only {t} tag(s) — min 3 recommended")
    elif t > 8:  warn(f"{t} tags — max 8 recommended")

    return data


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        err("Empty input")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        err(f"Invalid JSON: {e}")
    print(json.dumps(validate(data), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
