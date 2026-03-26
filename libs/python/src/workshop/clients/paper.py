"""Paper API client — full coverage of Core API endpoints.

Covers: Articles, Search, Digest, Annotations, Dashboard, Status.

Usage:
    from workshop.clients.paper import PaperClient

    client = PaperClient()
    articles = client.list_articles()
    results = client.search("retrieval augmented generation")
    digest = client.get_digest(article_id)
"""

from ._base import BaseClient


class PaperClient(BaseClient):
    """Client for the Paper academic research module (Core API port 10000)."""

    def __init__(self, **kwargs):
        super().__init__(module="paper", **kwargs)

    # ======================== Articles ========================

    def list_articles(
        self,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        category: str | None = None,
        relevance: str | None = None,
        cannibalize_candidate: bool | None = None,
    ) -> dict:
        """List articles with optional filters. GET /articles"""
        params: dict = {"page": page, "page_size": page_size}
        if tag:
            params["tag"] = tag
        if category:
            params["category"] = category
        if relevance:
            params["relevance"] = relevance
        if cannibalize_candidate is not None:
            params["cannibalize_candidate"] = cannibalize_candidate
        return self._get("/articles", params)

    def get_article(self, article_id: str) -> dict:
        """Get a single article by ID. GET /articles/{id}"""
        return self._get(f"/articles/{article_id}")

    def create_article(
        self,
        title: str,
        abstract: str | None = None,
        arxiv_id: str | None = None,
        doi: str | None = None,
        year: int | None = None,
        authors: list[str] | None = None,
        journal: str | None = None,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        pdf_url: str | None = None,
        source_url: str | None = None,
        full_text: str | None = None,
    ) -> dict:
        """Create a new article. POST /articles"""
        body: dict = {"title": title}
        if abstract is not None:
            body["abstract"] = abstract
        if arxiv_id is not None:
            body["arxiv_id"] = arxiv_id
        if doi is not None:
            body["doi"] = doi
        if year is not None:
            body["year"] = year
        if authors is not None:
            body["authors"] = authors
        if journal is not None:
            body["journal"] = journal
        if categories is not None:
            body["categories"] = categories
        if tags is not None:
            body["tags"] = tags
        if pdf_url is not None:
            body["pdf_url"] = pdf_url
        if source_url is not None:
            body["source_url"] = source_url
        if full_text is not None:
            body["full_text"] = full_text
        return self._post("/articles", body)

    def update_article(self, article_id: str, **fields) -> dict:
        """Update an article. PUT /articles/{id}

        Accepted fields: title, abstract, tags, categories, journal, year, authors,
        pdf_url, source_url, full_text.
        """
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/articles/{article_id}", body)

    def delete_article(self, article_id: str) -> None:
        """Delete an article (soft delete). DELETE /articles/{id}"""
        self._delete(f"/articles/{article_id}")

    # ======================== Search ========================

    def search(
        self,
        query: str,
        limit: int = 5,
        threshold: float | None = None,
        relevance_filter: str | None = None,
    ) -> list:
        """Semantic search over articles. POST /search"""
        body: dict = {"query": query, "limit": limit}
        if threshold is not None:
            body["threshold"] = threshold
        if relevance_filter is not None:
            body["relevance_filter"] = relevance_filter
        return self._post("/search", body)

    # ======================== Digest ========================

    def get_digest(self, article_id: str) -> dict:
        """Get the LLM digest for an article. GET /articles/{id}/digest"""
        return self._get(f"/articles/{article_id}/digest")

    def trigger_digest(
        self,
        article_id: str,
        model_name: str | None = None,
        force: bool = False,
    ) -> dict:
        """Trigger digest generation for an article. POST /articles/{id}/digest/trigger

        Args:
            article_id: Article UUID.
            model_name: Override the default LLM model for this digest.
            force: If True, regenerate even if a digest already exists.
        """
        body: dict = {}
        if model_name is not None:
            body["model_name"] = model_name
        if force:
            body["force"] = True
        return self._post(f"/articles/{article_id}/digest/trigger", body)

    def redigest(
        self,
        model_name: str | None = None,
        relevance_filter: str | None = None,
    ) -> dict:
        """Batch re-generate digests with a specific model. POST /digest/redigest

        Args:
            model_name: LLM model to use for regeneration (e.g. "claude-haiku-4-5").
            relevance_filter: Only redigest articles with this relevance level
                              ("high" | "medium" | "low"). None = all articles.
        """
        body: dict = {"model_name": model_name}
        if relevance_filter is not None:
            body["relevance_filter"] = relevance_filter
        return self._post("/digest/redigest", body)

    # ======================== Annotations ========================

    def list_annotations(self, article_id: str) -> list:
        """List annotations for an article. GET /articles/{id}/annotations"""
        return self._get(f"/articles/{article_id}/annotations")

    def create_annotation(
        self,
        article_id: str,
        note: str,
        annotation_type: str = "note",
        tags: list[str] | None = None,
    ) -> dict:
        """Create an annotation on an article. POST /articles/{id}/annotations

        Args:
            article_id: Article UUID.
            note: Annotation text.
            annotation_type: One of note/highlight/question/synthesis/action-taken.
            tags: Optional list of tags.
        """
        body: dict = {
            "note": note,
            "annotation_type": annotation_type,
        }
        if tags is not None:
            body["tags"] = tags
        return self._post(f"/articles/{article_id}/annotations", body)

    # ======================== Fetch ========================

    def fetch_arxiv(self, arxiv_url_or_id: str) -> dict:
        """Fetch and import a paper from arXiv. POST /fetch/arxiv

        Args:
            arxiv_url_or_id: Full arXiv URL or bare ID (e.g. "2401.12345").
        """
        return self._post("/fetch/arxiv", {"arxiv_url_or_id": arxiv_url_or_id})

    # ======================== Dashboard ========================

    def get_dashboard(self) -> dict:
        """Get dashboard summary. GET /dashboard"""
        return self._get("/dashboard")

    # ======================== Status ========================

    def status(self) -> dict:
        """Module status check. GET /status"""
        return self._get("/status")

    def health(self) -> bool:
        """Check API connectivity. Returns True if API responds."""
        try:
            self.status()
            return True
        except Exception:
            return False
