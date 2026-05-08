"""Predicate vocabulary and normalization.

Extracted from memvault/kg_config.py. Extended with register_predicates()
for domain-specific predicate expansion (e.g., docvault document relations).
"""

from __future__ import annotations

# 20 predicates in 7 categories (from V1 triple extraction)
PREDICATE_VOCABULARY: dict[str, list[str]] = {
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
VALID_PREDICATES: set[str] = {p for preds in PREDICATE_VOCABULARY.values() for p in preds}

# 40+ alias → canonical predicate mapping
PREDICATE_ALIASES: dict[str, str] = {
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
    # ---------------------------------------------------------------------
    # 中文 alias（subject/object 中文化重構，2026-05-08）
    # 讓 LLM 看到中文動詞時有路可選，不必再被迫翻譯成英文
    # ---------------------------------------------------------------------
    # Dependency
    "使用": "uses",
    "用": "uses",
    "用到": "uses",
    "採用": "uses",
    "需要": "requires",
    "得要": "requires",
    "必須有": "requires",
    "依賴": "depends_on",
    "靠": "depends_on",
    # Configuration
    "設定為": "configured_with",
    "搭配": "configured_with",
    "格式是": "format_is",
    "結構是": "format_is",
    "預設是": "default_is",
    "預設值": "default_is",
    # Causality
    "造成": "causes",
    "導致": "causes",
    "引發": "causes",
    "讓": "causes",
    "防止": "prevents",
    "避免": "prevents",
    "擋住": "prevents",
    "修復": "fixes",
    "修": "fixes",
    "解決": "fixes",
    "啟用": "enables",
    "開啟": "enables",
    "讓...能夠": "enables",
    # Prescriptive
    "該": "should",
    "應該": "should",
    "建議": "should",
    "不該": "should_NOT",
    "不應該": "should_NOT",
    "禁止": "should_NOT",
    "別": "should_NOT",
    # Pattern
    "模式是": "pattern_is",
    "套路是": "pattern_is",
    "走法是": "pattern_is",
    "流程是": "flow_is",
    "實作為": "implemented_as",
    "做成": "implemented_as",
    # Decision
    "選用": "chosen_over",
    "捨棄改用": "chosen_over",
    "替換成": "chosen_over",
    "原因是": "reason_for",
    "因為": "reason_for",
    "理由是": "reason_for",
    # Effect
    "提升": "improves",
    "改善": "improves",
    "讓...更好": "improves",
    "降低": "degrades",
    "削弱": "degrades",
    "讓...變差": "degrades",
    # Mapping
    "對應到": "maps_to",
    "等於": "maps_to",
    "對應": "maps_to",
}


def normalize_predicate(predicate: str) -> str:
    """Normalize a predicate to canonical form using alias mapping."""
    p = predicate.strip().lower()
    if p in VALID_PREDICATES:
        return p
    return PREDICATE_ALIASES.get(p, p)


def register_predicates(category: str, predicates: list[str]) -> None:
    """Register domain-specific predicates at runtime.

    Example:
        register_predicates("document", ["defines", "references", "summarizes"])
    """
    if category not in PREDICATE_VOCABULARY:
        PREDICATE_VOCABULARY[category] = []
    for p in predicates:
        if p not in VALID_PREDICATES:
            PREDICATE_VOCABULARY[category].append(p)
            VALID_PREDICATES.add(p)
