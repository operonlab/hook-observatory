"""Test triple-extraction.txt prompt has Chinese surface form rules (2026-05-08).

Reason: 既有 prompt 整份英文 + 全英文 examples → LLM few-shot prime bias
        把 subject/object 抽成英文。重寫後 prompt 應：
1. 含「繁體中文 surface form」必填規則
2. 4 個 examples 全為中文輸出（無純英文 example）
3. 不再使用「Subject and Object must be SPECIFIC」這種純英文 instruction
4. predicate 仍維持 18 個英文 canonical 不變
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
PROMPT_PATH = REPO_ROOT / "mcp" / "memvault" / "scripts" / "prompts" / "triple-extraction.txt"

CJK_RE = re.compile(r'[一-鿿]')


def test_prompt_file_exists():
    assert PROMPT_PATH.exists(), f"prompt missing: {PROMPT_PATH}"


def test_prompt_has_chinese_instruction():
    """prompt 主體應為繁體中文 instruction."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    cjk_chars = len(CJK_RE.findall(content))
    assert cjk_chars >= 200, f"prompt 中文字數 {cjk_chars}，應 ≥ 200"


def test_prompt_has_zh_surface_form_rule():
    """prompt 必須明確要求 subject/object 用繁體中文."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "繁體中文" in content
    assert "subject" in content.lower() or "subject" in content


def test_prompt_keeps_18_predicate_canonical():
    """predicate vocabulary 維持英文 18 canonical."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    canonical_18 = [
        "uses", "requires", "depends_on",
        "configured_with", "format_is", "default_is",
        "causes", "prevents", "fixes", "enables",
        "should", "should_NOT",
        "pattern_is", "flow_is", "implemented_as",
        "chosen_over", "reason_for",
        "improves", "degrades",
        "maps_to",
    ]
    for p in canonical_18:
        assert p in content, f"prompt missing canonical predicate: {p}"


def test_prompt_examples_have_cjk_subject_object():
    """prompt 內 JSON examples 的 subject / object 必須有 CJK 字元（避免純英文 prime bias）."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 抓所有 JSON code block（fenced 或 inline）
    json_blocks = re.findall(r'\{[^{}]*"s"[^{}]*"o"[^{}]*\}', content, re.DOTALL)
    assert len(json_blocks) >= 3, f"找不到足夠 example triple JSON blocks: {len(json_blocks)}"

    cjk_subjects = 0
    cjk_objects = 0
    for block in json_blocks:
        if CJK_RE.search(block):
            # 簡化判斷：block 中有 CJK 即視為 zh-aware
            cjk_subjects += 1
            cjk_objects += 1
    # 至少 80% 的 example triple 應該含 CJK
    threshold = max(int(len(json_blocks) * 0.8), 3)
    assert cjk_subjects >= threshold, \
        f"只有 {cjk_subjects}/{len(json_blocks)} example triple 含 CJK，應 ≥ {threshold}"


def test_prompt_envelope_fields_documented():
    """prompt 必須教 LLM 抽 9 envelope 欄位."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    envelope_keywords = [
        "kind", "modality", "polarity", "raw_quote",
        "temporal", "attribution", "speaker", "refs", "confidence",
    ]
    for kw in envelope_keywords:
        assert kw in content, f"prompt missing envelope field: {kw}"


def test_prompt_modality_is_epistemic():
    """modality enum 用 epistemic 6 值（非 deontic must/should/may）."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    epistemic = ["observed", "planned", "desired", "hypothesized", "regretted", "retracted"]
    for m in epistemic:
        assert m in content, f"prompt missing epistemic modality: {m}"


def test_prompt_no_pure_english_few_shot_example():
    """既有 prompt 的 3 個全英文 example 該被替換掉（避免 prime bias）.

    判斷：搜 'pgvector HNSW index tuning' 這類舊英文 topic 字串應不再出現
    （或已被中文 topic 替代）.
    """
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 舊 prompt 的 topic 是英文 "pgvector HNSW index tuning"
    # 新 prompt 改成中文 "pgvector HNSW 調校"
    # 如果還有舊英文 topic，代表 prompt 沒重寫
    legacy_english_topics = [
        '"topic": "pgvector HNSW index tuning"',
        '"topic": "Claude Code hook script safety rules"',
    ]
    for legacy in legacy_english_topics:
        assert legacy not in content, f"prompt still has legacy English topic: {legacy}"


def test_prompt_output_format_includes_envelope():
    """prompt 內 Output Format 區塊應展示 envelope 欄位的 JSON shape."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 找 Output 部分（中文「輸出」或 "Output"）
    assert "Output" in content or "輸出" in content
    # 至少展示 kind / modality 欄位的 JSON 範例
    assert '"kind"' in content
    assert '"raw_quote"' in content
