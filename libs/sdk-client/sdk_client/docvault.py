"""DocVault API client — full coverage of document QA, CRUD, relations, coverage gaps.

Usage:
    from sdk_client.docvault import DocvaultClient

    client = DocvaultClient()
    doc = client.upload(file_path="/path/to/doc.pdf", title="My Doc")
    result = client.qa("What does the document say about X?")
    gaps = client.list_gaps(status="pending")
"""

from pathlib import Path

from ._base import BaseClient


class DocvaultClient(BaseClient):
    """Client for the DocVault document knowledge system (Core API port 10000)."""

    def __init__(self, **kwargs):
        super().__init__(module="docvault", **kwargs)

    # ======================== Documents CRUD ========================

    def upload(
        self,
        file_path: str,
        title: str,
        *,
        source_type: str | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Upload a document file. POST /documents

        Reads the file, computes content hash, and creates a document + first version.
        """
        import hashlib

        path = Path(file_path)
        data = path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()

        if source_type is None:
            ext_map = {".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".txt": "txt"}
            source_type = ext_map.get(path.suffix.lower(), "txt")

        body: dict = {
            "title": title,
            "source_type": source_type,
            "content_hash": content_hash,
            "source_uri": str(path.resolve()),
            "tags": tags or [],
        }
        if metadata:
            body["metadata"] = metadata
        return self._post("/documents", body)

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        status: str | None = None,
        source_type: str | None = None,
        tag: str | None = None,
    ) -> dict:
        """List documents with optional filters. GET /documents"""
        params: dict = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        if source_type:
            params["source_type"] = source_type
        if tag:
            params["tag"] = tag
        return self._get("/documents", params)

    def get_document(self, doc_id: str) -> dict:
        """Get document details. GET /documents/{id}"""
        return self._get(f"/documents/{doc_id}")

    def update_document(self, doc_id: str, **fields) -> dict:
        """Update document fields. PATCH /documents/{id}

        Accepted fields: title, tags, metadata, status.
        """
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/documents/{doc_id}", body)

    def delete_document(self, doc_id: str) -> None:
        """Soft-delete a document. DELETE /documents/{id}"""
        self._delete(f"/documents/{doc_id}")

    def supersede_document(
        self,
        doc_id: str,
        file_path: str,
    ) -> dict:
        """Upload a new version of an existing document. POST /documents/{id}/supersede

        Triggers version replacement flow: hash compare → new version → re-index.
        """
        import hashlib

        path = Path(file_path)
        data = path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        raw_content = data.decode("utf-8", errors="replace")

        return self._post(
            f"/documents/{doc_id}/supersede",
            {"raw_content": raw_content, "content_hash": content_hash},
        )

    # ======================== Versions ========================

    def list_versions(self, doc_id: str) -> list[dict]:
        """List all versions of a document. GET /documents/{id}/versions"""
        return self._get(f"/documents/{doc_id}/versions")

    def get_version(self, version_id: str) -> dict:
        """Get a specific document version. GET /versions/{id}"""
        return self._get(f"/versions/{version_id}")

    # ======================== Search + QA ========================

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        source_type: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        """Semantic search across document chunks. GET /search"""
        params: dict = {"q": query, "top_k": top_k}
        if source_type:
            params["source_type"] = source_type
        if tag:
            params["tag"] = tag
        return self._get("/search", params)

    def qa(
        self,
        question: str,
        *,
        mode: str = "factual",
        top_k: int = 5,
        domain: str = "default",
    ) -> dict:
        """Ask a question against the document knowledge base. POST /qa

        Args:
            question: The question to answer.
            mode: "factual" (Pipeline A) or "mixed" (Pipeline C).
            top_k: Number of evidence chunks to use.
            domain: Domain profile for pipeline configuration.
        """
        return self._post(
            "/qa",
            {
                "question": question,
                "mode": mode,
                "top_k": top_k,
                "domain": domain,
            },
        )

    def qa_feedback(self, qa_log_id: str, feedback: str) -> dict:
        """Submit feedback on a QA answer. POST /qa/{id}/feedback

        Args:
            qa_log_id: ID of the QA log entry.
            feedback: "positive" or "negative".
        """
        return self._post(f"/qa/{qa_log_id}/feedback", {"feedback": feedback})

    # ======================== Relations ========================

    def list_relations(self, doc_id: str) -> list[dict]:
        """List relations for a document. GET /documents/{id}/relations"""
        return self._get(f"/documents/{doc_id}/relations")

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        *,
        evidence: str | None = None,
        confidence: float = 0.0,
    ) -> dict:
        """Create a document relation. POST /relations"""
        body: dict = {
            "source_document_id": source_id,
            "target_document_id": target_id,
            "relation_type": relation_type,
            "confidence": confidence,
        }
        if evidence:
            body["evidence"] = evidence
        return self._post("/relations", body)

    def find_contradictions(self, doc_id: str | None = None) -> list[dict]:
        """Find contradicting document pairs. GET /contradictions"""
        params: dict = {}
        if doc_id:
            params["doc_id"] = doc_id
        return self._get("/contradictions", params)

    # ======================== Coverage Gaps ========================

    def list_gaps(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        status: str | None = None,
    ) -> dict:
        """List coverage gaps. GET /gaps"""
        params: dict = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        return self._get("/gaps", params)

    def resolve_gap(self, gap_id: str, resolution: str) -> dict:
        """Resolve a coverage gap. PATCH /gaps/{id}"""
        return self._put(f"/gaps/{gap_id}", {"status": "resolved", "resolution": resolution})

    def gap_stats(self) -> dict:
        """Get coverage gap statistics. GET /gaps/stats"""
        return self._get("/gaps/stats")

    # ======================== Admin ========================

    def reindex(self, doc_id: str) -> dict:
        """Queue a document for re-indexing. POST /documents/{id}/reindex"""
        return self._post(f"/documents/{doc_id}/reindex", {})

    def bulk_import(self, file_paths: list[str]) -> list[dict]:
        """Bulk import multiple documents. POST /bulk-import

        Returns a list of results (success/failure per file).
        """
        results = []
        for fp in file_paths:
            try:
                path = Path(fp)
                doc = self.upload(fp, title=path.stem)
                results.append({"file": fp, "status": "success", "document": doc})
            except Exception as e:
                results.append({"file": fp, "status": "error", "error": str(e)})
        return results

    def export(self, doc_id: str, fmt: str = "markdown") -> str:
        """Export document content. GET /documents/{id}/export"""
        return self._get(f"/documents/{doc_id}/export", {"format": fmt})

    def stats(self) -> dict:
        """Get docvault statistics. GET /stats"""
        return self._get("/stats")

    # ======================== QA Logs ========================

    def list_qa_logs(self, page: int = 1, page_size: int = 20) -> dict:
        """List QA log entries. GET /qa-logs"""
        return self._get("/qa-logs", {"page": page, "page_size": page_size})
