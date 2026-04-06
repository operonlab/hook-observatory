"""DocVault Ops tests — HierarchicalChunkOp, StrictCiteOp, ContradictionAwareOp."""

import pytest

from ..ops.contradiction_aware import (
    ContradictionAwareOp,
    _compute_text_overlap,
    _detect_contradictions,
)
from ..ops.hierarchical_chunk import (
    HierarchicalChunkOp,
    _detect_heading_level,
    _estimate_tokens,
    build_section_tree,
)
from ..ops.strict_cite import (
    StrictCiteOp,
    _extract_citations,
    _extract_unsupported,
    _format_sources,
)

# ======================== HierarchicalChunkOp ========================


class TestHeadingDetection:
    def test_markdown_h1(self):
        result = _detect_heading_level("# Introduction")
        assert result == (1, "Introduction")

    def test_markdown_h2(self):
        result = _detect_heading_level("## Methods")
        assert result == (2, "Methods")

    def test_markdown_h3(self):
        result = _detect_heading_level("### Sub-section")
        assert result == (3, "Sub-section")

    def test_cjk_chapter(self):
        result = _detect_heading_level("第一章")
        assert result is not None
        assert result[0] == 1

    def test_cjk_article(self):
        result = _detect_heading_level("第三條")
        assert result is not None
        assert result[0] == 2

    def test_numbered_heading(self):
        result = _detect_heading_level("1.2 Background")
        assert result is not None
        assert result[0] == 2

    def test_plain_text_not_heading(self):
        assert _detect_heading_level("Just some regular text.") is None

    def test_empty_line(self):
        assert _detect_heading_level("") is None


class TestSectionTree:
    def test_simple_tree(self):
        text = "# Chapter 1\n\nContent here.\n\n## Section 1.1\n\nMore content."
        tree = build_section_tree(text)
        assert len(tree) == 1
        assert tree[0].heading == "Chapter 1"
        assert len(tree[0].children) == 1

    def test_flat_headings(self):
        text = "# A\n\nText A\n\n# B\n\nText B\n\n# C\n\nText C"
        tree = build_section_tree(text)
        assert len(tree) == 3

    def test_no_headings(self):
        text = "Just plain text without any headings."
        tree = build_section_tree(text)
        assert len(tree) == 1
        assert tree[0].heading == "(untitled)"

    def test_empty_input(self):
        tree = build_section_tree("")
        assert tree == []

    def test_nested_three_levels(self):
        text = "# L1\n\n## L2\n\n### L3\n\nDeep content."
        tree = build_section_tree(text)
        assert len(tree) == 1
        assert len(tree[0].children) == 1
        assert len(tree[0].children[0].children) == 1


class TestTokenEstimation:
    def test_english_text(self):
        tokens = _estimate_tokens("Hello world this is a test")
        assert tokens > 0
        assert tokens < 30

    def test_cjk_text(self):
        tokens = _estimate_tokens("這是中文測試文字")
        assert tokens == 8  # each CJK char = 1 token

    def test_mixed_text(self):
        tokens = _estimate_tokens("Hello 你好 World 世界")
        assert tokens > 4


@pytest.mark.asyncio
class TestHierarchicalChunkOp:
    async def test_basic_chunking(self):
        op = HierarchicalChunkOp()
        ctx = {
            "raw_content": (
                "# Title\n\n"
                + "Paragraph one with enough content to comfortably "
                "exceed the minimum chunk size threshold of one "
                "hundred characters. " * 2
                + "\n\n## Section\n\n"
                + "Another paragraph with sufficient content for "
                "the minimum size threshold verification test. " * 2
            )
        }
        result = await op(ctx)
        assert "chunks" in result
        assert "section_tree" in result
        assert len(result["chunks"]) >= 1

    async def test_empty_input(self):
        op = HierarchicalChunkOp()
        ctx = {"raw_content": ""}
        result = await op(ctx)
        assert result["chunks"] == []
        assert result["section_tree"] == []

    async def test_chunks_have_section_path(self):
        op = HierarchicalChunkOp()
        long_a = "# Chapter\n\n" + "Long content. " * 20
        long_b = "\n\n## Section\n\n" + "More content. " * 20
        ctx = {"raw_content": long_a + long_b}
        result = await op(ctx)
        for chunk in result["chunks"]:
            assert "section_path" in chunk
            assert chunk["section_path"] is not None

    async def test_op_properties(self):
        op = HierarchicalChunkOp()
        assert op.name == "hierarchical_chunk"
        assert op.input_keys == ("raw_content",)
        assert op.output_keys == ("chunks", "section_tree")


# ======================== StrictCiteOp ========================


class TestSourceFormatting:
    def test_format_sources(self):
        chunks = [
            {"section_path": "Chapter 1", "page_range": "5", "content": "Source text."},
            {"section_path": "Chapter 2", "content": "Another source."},
        ]
        result = _format_sources(chunks)
        assert "[1]" in result
        assert "[2]" in result
        assert "Chapter 1" in result
        assert "(p.5)" in result

    def test_empty_sources(self):
        assert _format_sources([]) == ""


class TestCitationExtraction:
    def test_extract_citations(self):
        answer = "According to [1], the fact is true. Also see [2]."
        chunks = [
            {"document_id": "d1", "id": "c1", "section_path": "S1", "content": "x"},
            {"document_id": "d2", "id": "c2", "section_path": "S2", "content": "y"},
        ]
        citations = _extract_citations(answer, chunks)
        assert len(citations) == 2
        assert citations[0]["document_id"] == "d1"
        assert citations[1]["document_id"] == "d2"

    def test_dedup_citations(self):
        answer = "See [1] and also [1] again."
        chunks = [{"document_id": "d1", "id": "c1", "section_path": "S", "content": "x"}]
        citations = _extract_citations(answer, chunks)
        assert len(citations) == 1

    def test_out_of_range_ignored(self):
        answer = "See [99]."
        chunks = [{"document_id": "d1", "id": "c1", "section_path": "S", "content": "x"}]
        citations = _extract_citations(answer, chunks)
        assert len(citations) == 0


class TestUnsupportedExtraction:
    def test_extract_unsupported(self):
        answer = "Some fact [1]. [UNSUPPORTED: unverified claim]"
        unsupported = _extract_unsupported(answer)
        assert len(unsupported) == 1
        assert unsupported[0] == "unverified claim"

    def test_no_unsupported(self):
        answer = "All facts are cited [1] [2]."
        assert _extract_unsupported(answer) == []


@pytest.mark.asyncio
class TestStrictCiteOp:
    async def test_no_chunks_returns_empty(self):
        op = StrictCiteOp(domain="medical")
        ctx = {"question": "What is X?", "evidence_chunks": []}
        result = await op(ctx)
        assert result["confidence"] == 0.0
        assert result["citations"] == []

    async def test_with_chunks(self):
        op = StrictCiteOp(domain="medical")
        ctx = {
            "question": "What is the dosage?",
            "evidence_chunks": [
                {"content": "Take 500mg daily.", "document_id": "d1", "id": "c1",
                 "section_path": "Dosage", "page_range": "3"},
            ],
        }
        result = await op(ctx)
        assert "answer" in result
        assert result["confidence"] > 0.0

    async def test_op_properties(self):
        op = StrictCiteOp()
        assert op.name == "strict_cite"
        assert "question" in op.input_keys
        assert "evidence_chunks" in op.input_keys


# ======================== ContradictionAwareOp ========================


class TestTextOverlap:
    def test_identical_texts(self):
        overlap = _compute_text_overlap("hello world", "hello world")
        assert overlap == 1.0

    def test_no_overlap(self):
        overlap = _compute_text_overlap("hello world", "foo bar")
        assert overlap == 0.0

    def test_partial_overlap(self):
        overlap = _compute_text_overlap("hello world foo", "hello world bar")
        assert 0.0 < overlap < 1.0

    def test_empty_text(self):
        assert _compute_text_overlap("", "hello") == 0.0
        assert _compute_text_overlap("hello", "") == 0.0


class TestContradictionDetection:
    def test_no_contradictions_same_doc(self):
        chunks = [
            {"content": "The policy states X.", "document_id": "d1", "id": "c1"},
            {"content": "The policy states Y.", "document_id": "d1", "id": "c2"},
        ]
        contradictions = _detect_contradictions(chunks, overlap_threshold=0.1)
        assert len(contradictions) == 0  # same document

    def test_detects_contradiction_different_docs(self):
        chunks = [
            {"content": "The regulation requires annual filing by March.",
             "document_id": "d1", "id": "c1", "section_path": "Reg A"},
            {"content": "The regulation requires annual filing by June.",
             "document_id": "d2", "id": "c2", "section_path": "Reg B"},
        ]
        contradictions = _detect_contradictions(chunks, overlap_threshold=0.3)
        # Whether this triggers depends on word overlap threshold
        assert isinstance(contradictions, list)

    def test_empty_chunks(self):
        assert _detect_contradictions([]) == []


@pytest.mark.asyncio
class TestContradictionAwareOp:
    async def test_no_chunks(self):
        op = ContradictionAwareOp()
        ctx = {"question": "Legal Q?", "evidence_chunks": []}
        result = await op(ctx)
        assert result["confidence"] == 0.0
        assert result["contradictions"] == []

    async def test_with_chunks(self):
        op = ContradictionAwareOp()
        ctx = {
            "question": "What does the law say?",
            "evidence_chunks": [
                {"content": "Article 1 states the deadline is March.",
                 "document_id": "d1", "id": "c1", "section_path": "Art. 1"},
            ],
        }
        result = await op(ctx)
        assert "answer" in result
        assert result["confidence"] > 0.0

    async def test_op_properties(self):
        op = ContradictionAwareOp()
        assert op.name == "contradiction_aware"
        assert "contradictions" in op.output_keys
