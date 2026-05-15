"""Assistant API client — cross-vault QA via the router (Core API port 10000).

Pairs with core/src/modules/assistant/cross_vault_service.py.

Usage::

    from sdk_client.assistant import AssistantClient

    client = AssistantClient(space_id="default", timeout=180)
    res = client.qa("我之前說過什麼關於 memvault？")
    print(res["answer"])
    for c in res["citations"]:
        print(c["source"], c.get("section") or c.get("block_content","")[:60])
"""

from ._base import BaseClient


class AssistantClient(BaseClient):
    """Client for the unified cross-vault QA endpoint."""

    def __init__(self, **kwargs):
        super().__init__(module="assistant", **kwargs)

    def qa(
        self,
        question: str,
        *,
        routing: str = "auto",
        docvault_space: str | None = None,
        memvault_top_k: int = 5,
        docvault_top_k: int = 20,
        docvault_tags: list[str] | None = None,
        docvault_mode: str = "factual",
        session_id: str | None = None,
    ) -> dict:
        """Run a cross-vault QA question.

        Args:
            question: free-form natural language query
            routing: "auto" (LLM classifies) | "memory" | "doc" | "mixed"
            docvault_space: override docvault space_id (memvault always uses caller space)
            memvault_top_k: max memvault blocks to retrieve
            docvault_top_k: max docvault chunks to retrieve
            docvault_tags: optional tag filter (AND semantics)
            docvault_mode: docvault QA pipeline mode (factual or mixed)
            session_id: optional caller session id for QA log threading

        Returns: parsed JSON with keys
            question, answer, routing_decision, routing_model, routing_fallback,
            memvault_hits, docvault_hits, citations (list of source-tagged dicts),
            docvault_qa_log_id.
        """
        body: dict = {
            "question": question,
            "routing": routing,
            "memvault_top_k": memvault_top_k,
            "docvault_top_k": docvault_top_k,
            "docvault_mode": docvault_mode,
        }
        if docvault_space is not None:
            body["docvault_space"] = docvault_space
        if docvault_tags is not None:
            body["docvault_tags"] = docvault_tags
        if session_id is not None:
            body["session_id"] = session_id
        return self._post("/qa", body)
