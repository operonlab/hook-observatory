"""DocVault API client — full coverage of all Core API endpoints.

Usage:
    from sdk_client.docvault import DocvaultClient

    client = DocvaultClient()
    results = client.search("Python concurrency patterns")
    answer = client.qa("What is the GIL?")
    client.upload("/path/to/doc.pdf", title="Python GIL Guide")
"""

from ._base import BaseClient


class DocvaultClient(BaseClient):
    """Client for the DocVault document knowledge system (Core API port 10000)."""

    def __init__(self, **kwargs):
        super().__init__(module="docvault", **kwargs)

    # ======================== Documents CRUD ========================

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        tags: str | None = None,
        status: str | None = None,
    ) -> dict:
        """List documents with optional filters. GET /documents"""
        params: dict = {"page": page, "page_size": page_size}
        if tag:
            params["tag"] = tag
        if tags:
            params["tags"] = tags
        if status:
            params["status"] = status
        return self._get("/documents", params)

    def get_document(self, document_id: str) -> dict:
        """Get a single document by ID. GET /documents/{id}"""
        return self._get(f"/documents/{document_id}")

    def upload(
        self,
        file_path: str | None = None,
        title: str | None = None,
        source_type: str | None = None,
        source_uri: str | None = None,
        content_hash: str | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Upload a document file — full server-side pipeline. POST /documents/upload

        If file_path is provided, the server parses, chunks, and indexes it.
        Falls back to POST /documents for metadata-only creation.
        """
        if file_path:
            from pathlib import Path

            path = Path(file_path)
            body: dict = {
                "file_path": str(path.resolve()),
                "tags": tags or [],
            }
            if title:
                body["title"] = title
            if source_type:
                body["source_type"] = source_type
            if source_uri:
                body["source_uri"] = source_uri
            if metadata:
                body["metadata"] = metadata
            return self._post("/documents/upload", body)

        # Metadata-only creation (no file)

        body = {
            "source_type": source_type or "markdown",
            "tags": tags or [],
            "title": title or "Untitled",
            "content_hash": content_hash or "0" * 16,
        }
        if source_uri:
            body["source_uri"] = source_uri
        if metadata:
            body["metadata"] = metadata
        return self._post("/documents", body)

    def update_document(self, document_id: str, **fields) -> dict:
        """Update a document. PUT /documents/{id}

        Accepted fields: title, tags, metadata, status, confidence.
        """
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/documents/{document_id}", body)

    def delete_document(self, document_id: str) -> None:
        """Delete a document. DELETE /documents/{id}"""
        self._delete(f"/documents/{document_id}")

    # ======================== Supersede ========================

    def supersede_document(
        self,
        document_id: str,
        new_document_id: str,
        reason: str | None = None,
    ) -> dict:
        """Mark a document as superseded by a newer one. POST /documents/{id}/supersede"""
        body: dict = {"new_document_id": new_document_id}
        if reason:
            body["reason"] = reason
        return self._post(f"/documents/{document_id}/supersede", body)

    # ======================== Versions ========================

    def list_versions(
        self,
        document_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List versions of a document. GET /documents/{id}/versions"""
        return self._get(
            f"/documents/{document_id}/versions",
            {"page": page, "page_size": page_size},
        )

    # ======================== Chunks ========================

    def list_chunks(
        self,
        document_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """List chunks of a document. GET /documents/{id}/chunks"""
        return self._get(
            f"/documents/{document_id}/chunks",
            {"page": page, "page_size": page_size},
        )

    # ======================== Search ========================

    def search(
        self,
        query: str,
        top_k: int = 10,
        source_type: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Semantic search over document chunks. POST /search"""
        body: dict = {"q": query, "top_k": top_k}
        if source_type:
            body["source_type"] = source_type
        if tags:
            body["tags"] = tags
        return self._post("/search", body)

    # ======================== QA ========================

    def qa(
        self,
        question: str,
        mode: str = "factual",
        domain: str = "default",
        top_k: int = 6,
    ) -> dict:
        """Ask a question against document corpus. POST /qa"""
        return self._post(
            "/qa",
            {
                "question": question,
                "mode": mode,
                "domain": domain,
                "top_k": top_k,
            },
        )

    def qa_feedback(self, qa_log_id: str, feedback: str) -> dict:
        """Record QA feedback (positive/negative). PATCH /qa/logs/{id}/feedback"""
        return self._patch(f"/qa/logs/{qa_log_id}/feedback", {"feedback": feedback})

    def list_qa_logs(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List QA log entries. GET /qa/logs"""
        return self._get("/qa/logs", {"page": page, "page_size": page_size})

    def get_qa_log(self, qa_log_id: str) -> dict:
        """Get a single QA log entry. GET /qa/logs/{id}"""
        return self._get(f"/qa/logs/{qa_log_id}")

    # ======================== Relations ========================

    def list_relations(
        self,
        document_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List relations for a document. GET /documents/{id}/relations"""
        return self._get(
            f"/documents/{document_id}/relations",
            {"page": page, "page_size": page_size},
        )

    def create_relation(
        self,
        source_document_id: str,
        target_document_id: str,
        relation_type: str,
        evidence: str | None = None,
        confidence: float | None = None,
    ) -> dict:
        """Create a document relation. POST /documents/{source_id}/relations"""
        body: dict = {
            "source_document_id": source_document_id,
            "target_document_id": target_document_id,
            "relation_type": relation_type,
        }
        if evidence:
            body["evidence"] = evidence
        if confidence is not None:
            body["confidence"] = confidence
        return self._post(f"/documents/{source_document_id}/relations", body)

    def find_contradictions(
        self,
        document_id: str | None = None,
    ) -> dict:
        """Find contradictions across documents. GET /relations/contradictions"""
        params: dict = {}
        if document_id:
            params["document_id"] = document_id
        return self._get("/relations/contradictions", params)

    # ======================== Coverage Gaps ========================

    def list_gaps(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> dict:
        """List coverage gaps. GET /gaps"""
        params: dict = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        return self._get("/gaps", params)

    def resolve_gap(
        self,
        gap_id: str,
        resolution: str = "document_added",
        resolved_document_id: str | None = None,
    ) -> dict:
        """Resolve a coverage gap. PATCH /gaps/{id}"""
        body: dict = {"status": "resolved", "resolution": resolution}
        if resolved_document_id:
            body["resolved_document_id"] = resolved_document_id
        return self._patch(f"/gaps/{gap_id}", body)

    def gap_stats(self) -> dict:
        """Get coverage gap statistics. GET /gaps/stats"""
        return self._get("/gaps/stats")

    # ======================== Management ========================

    def reindex(self, document_id: str | None = None) -> dict:
        """Trigger reindexing. POST /reindex

        If document_id is provided, reindex only that document.
        Otherwise, reindex all documents.
        """
        body: dict = {}
        if document_id:
            body["document_id"] = document_id
        return self._post("/reindex", body)

    def bulk_import(
        self,
        source_dir: str,
        source_type: str = "markdown",
        tags: list[str] | None = None,
    ) -> dict:
        """Bulk import documents from a directory. POST /bulk-import"""
        return self._post(
            "/bulk-import",
            {
                "source_dir": source_dir,
                "source_type": source_type,
                "tags": tags or [],
            },
        )

    def stats(self) -> dict:
        """Get docvault statistics. GET /dashboard"""
        return self._get("/dashboard")

    def health(self) -> bool:
        """Check API connectivity. GET /status"""
        try:
            self._get("/status")
            return True
        except Exception:
            return False
