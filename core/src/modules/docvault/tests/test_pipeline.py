"""DocVault pipeline integration tests — domain profile assembly + Op composition."""

import pytest

from ..domain_profiles import (
    build_ingest_pipeline_config,
    build_qa_pipeline_config,
    resolve_op,
)
from ..ops.contradiction_aware import ContradictionAwareOp
from ..ops.hierarchical_chunk import HierarchicalChunkOp
from ..ops.strict_cite import StrictCiteOp

# ======================== Pipeline Config Assembly ========================


class TestQAPipelineConfig:
    def test_default_config(self):
        config = build_qa_pipeline_config("default")
        assert config["domain"] == "default"
        assert "search" in config["slots"]
        assert "rerank" in config["slots"]
        assert "synth" in config["slots"]
        assert len(config["fixed_ops"]) >= 4

    def test_legal_config(self):
        config = build_qa_pipeline_config("legal")
        assert config["slots"]["synth"] == "ContradictionAwareOp"

    def test_medical_config(self):
        config = build_qa_pipeline_config("medical")
        assert config["slots"]["synth"] == "StrictCiteOp"

    def test_finance_config(self):
        config = build_qa_pipeline_config("finance")
        assert config["domain"] == "finance"


class TestIngestPipelineConfig:
    def test_default_ingest(self):
        config = build_ingest_pipeline_config("default")
        assert "chunk" in config["slots"]
        assert "index" in config["slots"]
        assert "DocumentParserOp" in config["fixed_ops"]
        assert "EnrichmentOp" in config["fixed_ops"]

    def test_legal_ingest_uses_hierarchical(self):
        config = build_ingest_pipeline_config("legal")
        assert config["slots"]["chunk"] == "HierarchicalChunkOp"


# ======================== Op Resolution + Instantiation ========================


class TestOpResolution:
    def test_resolve_hierarchical_chunk(self):
        cls = resolve_op("HierarchicalChunkOp")
        assert cls is HierarchicalChunkOp

    def test_resolve_strict_cite(self):
        cls = resolve_op("StrictCiteOp")
        assert cls is StrictCiteOp

    def test_resolve_contradiction_aware(self):
        cls = resolve_op("ContradictionAwareOp")
        assert cls is ContradictionAwareOp

    def test_instantiate_resolved_ops(self):
        """Resolved Ops should be instantiable with no args."""
        for op_name in ("HierarchicalChunkOp", "StrictCiteOp", "ContradictionAwareOp"):
            cls = resolve_op(op_name)
            assert cls is not None
            instance = cls()
            assert hasattr(instance, "name")
            assert hasattr(instance, "input_keys")
            assert hasattr(instance, "output_keys")
            assert callable(instance)


# ======================== End-to-End Pipeline Simulation ========================


@pytest.mark.asyncio
class TestPipelineE2E:
    """Simulate a domain-specific pipeline run using resolved Ops."""

    async def test_legal_pipeline_chunk_then_synth(self):
        """Legal pipeline: HierarchicalChunk → ContradictionAware."""
        # Step 1: Chunk
        chunk_op = HierarchicalChunkOp()
        ctx = {
            "raw_content": (
                "# 第一章 總則\n\n"
                "本法規定企業須於三月底前完成年度申報。" * 5 + "\n\n"
                "# 第二章 罰則\n\n"
                "違反者處以新台幣十萬元罰鍰。" * 5
            )
        }
        ctx = await chunk_op(ctx)
        assert len(ctx["chunks"]) >= 1
        assert ctx["section_tree"]  # should have tree structure

        # Step 2: Synth (with chunks as evidence)
        synth_op = ContradictionAwareOp()
        ctx["question"] = "企業申報截止日是什麼時候?"
        ctx["evidence_chunks"] = ctx["chunks"]
        ctx = await synth_op(ctx)
        assert "answer" in ctx
        assert isinstance(ctx["contradictions"], list)

    async def test_medical_pipeline_synth(self):
        """Medical pipeline: StrictCite with evidence chunks."""
        synth_op = StrictCiteOp(domain="medical")
        ctx = {
            "question": "What is the recommended dosage?",
            "evidence_chunks": [
                {
                    "content": "The recommended dosage is 500mg twice daily for adults.",
                    "document_id": "doc1",
                    "id": "chunk1",
                    "section_path": "Dosage > Adults",
                    "page_range": "12",
                },
                {
                    "content": "For pediatric patients, reduce dosage to 250mg once daily.",
                    "document_id": "doc1",
                    "id": "chunk2",
                    "section_path": "Dosage > Pediatric",
                    "page_range": "13",
                },
            ],
        }
        ctx = await synth_op(ctx)
        assert ctx["confidence"] > 0.0
        assert len(ctx["citations"]) >= 1

    async def test_all_profiles_have_resolvable_ops_for_phase5(self):
        """Phase 5 Ops (hierarchical_chunk, strict_cite, contradiction_aware) must resolve."""
        phase5_ops = {"HierarchicalChunkOp", "StrictCiteOp", "ContradictionAwareOp"}
        for op_name in phase5_ops:
            cls = resolve_op(op_name)
            assert cls is not None, f"{op_name} not resolvable"
            instance = cls()
            assert instance.name, f"{op_name} has no name"
