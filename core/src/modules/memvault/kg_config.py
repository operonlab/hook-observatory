"""Memvault KG constants — predicate vocabulary, categories, and enums."""

# 20 predicates in 7 categories (from V1 triple extraction)
PREDICATE_VOCABULARY = {
    "dependency": ["uses", "requires", "depends_on"],
    "config": ["configured_with", "format_is", "default_is"],
    "causation": ["causes", "prevents", "fixes", "enables"],
    "normative": ["should", "should_NOT"],
    "pattern": ["pattern_is", "flow_is", "implemented_as"],
    "decision": ["chosen_over", "reason_for"],
    "effect": ["improves", "degrades"],
    "mapping": ["maps_to"],
}

# Flatten for validation
VALID_PREDICATES = {p for preds in PREDICATE_VOCABULARY.values() for p in preds}

# 40+ alias → canonical predicate mapping
# From V1 validate-triples.py
PREDICATE_ALIASES = {
    "depends on": "depends_on",
    "needs": "requires",
    "need": "requires",
    "is configured with": "configured_with",
    "configured with": "configured_with",
    "configures": "configured_with",
    "config_is": "configured_with",
    "has_format": "format_is",
    "defaults_to": "default_is",
    "default": "default_is",
    "caused_by": "causes",
    "leads_to": "causes",
    "triggers": "causes",
    "avoids": "prevents",
    "blocks": "prevents",
    "solves": "fixes",
    "fixed_by": "fixes",
    "resolves": "fixes",
    "allows": "enables",
    "unlocks": "enables",
    "supports": "enables",
    "must": "should",
    "should_use": "should",
    "recommended": "should",
    "must_not": "should_NOT",
    "should_not": "should_NOT",
    "avoid": "should_NOT",
    "do_not": "should_NOT",
    "dont": "should_NOT",
    "implemented_by": "implemented_as",
    "built_with": "implemented_as",
    "runs_on": "implemented_as",
    "works_as": "pattern_is",
    "follows": "pattern_is",
    "architecture_is": "pattern_is",
    "pipeline_is": "flow_is",
    "workflow_is": "flow_is",
    "preferred_over": "chosen_over",
    "replaced_by": "chosen_over",
    "selected_over": "chosen_over",
    "because": "reason_for",
    "motivation": "reason_for",
    "speeds_up": "improves",
    "optimizes": "improves",
    "enhances": "improves",
    "slows_down": "degrades",
    "hurts": "degrades",
    "worsens": "degrades",
    "equivalent_to": "maps_to",
    "corresponds_to": "maps_to",
    "translates_to": "maps_to",
}

# ---------------------------------------------------------------------------
# Block Types — canonical vocabulary for MemoryBlock.block_type
# ---------------------------------------------------------------------------
BLOCK_TYPES = frozenset({"knowledge", "skill", "attitude", "general"})

# Block types protected from GRC curation even with low confidence scores.
# These represent high-value user corrections/decisions that should be preserved.
PROTECTED_BLOCK_TYPES = frozenset({"lesson", "correction", "decision", "rule"})

ATTITUDE_CATEGORIES = [
    "workflow",
    "tool_behavior",
    "config",
    "architecture",
    "preference",
    "testing_philosophy",
    "autonomy_level",
    "safety",
    "design_preference",
    "system_feedback",
]

SKILL_OUTCOMES = ["success", "failure", "partial", "unknown"]
ATTITUDE_OPERATIONS = ["ADD", "UPDATE", "NOOP"]


def normalize_predicate(predicate: str) -> str:
    """Normalize a predicate to canonical form using alias mapping."""
    p = predicate.strip().lower()
    if p in VALID_PREDICATES:
        return p
    return PREDICATE_ALIASES.get(p, p)
