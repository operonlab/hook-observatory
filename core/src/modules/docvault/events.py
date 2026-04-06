"""DocVault event types — {module}.{entity}.{past_tense}"""


class DocvaultEvents:
    # Lifecycle
    DOCUMENT_CREATED = "docvault.document.created"
    DOCUMENT_PROCESSING = "docvault.document.processing"
    DOCUMENT_INDEXED = "docvault.document.indexed"
    DOCUMENT_ENRICHED = "docvault.document.enriched"
    DOCUMENT_PUBLISHED = "docvault.document.published"
    DOCUMENT_SUPERSEDED = "docvault.document.superseded"
    DOCUMENT_ARCHIVED = "docvault.document.archived"
    # Query
    QA_EXECUTED = "docvault.qa.executed"
    QA_FEEDBACK = "docvault.qa.feedback"
    # Coverage
    COVERAGE_GAP_DETECTED = "docvault.coverage.gap_detected"
    COVERAGE_GAP_RESOLVED = "docvault.coverage.gap_resolved"
    # Relation
    RELATION_DISCOVERED = "docvault.relation.discovered"
