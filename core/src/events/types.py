"""Event type constants — {domain}.{entity}.{past_tense}"""


class AuthEvents:
    USER_REGISTERED = "auth.user.registered"
    USER_LOGGED_IN = "auth.user.logged_in"
    USER_LOGGED_OUT = "auth.user.logged_out"
    USER_STATUS_CHANGED = "auth.user.status_changed"
    ROLE_ASSIGNED = "auth.role.assigned"
    OAUTH_LINKED = "auth.oauth.linked"
    SESSION_CREATED = "auth.session.created"
    SESSION_REVOKED = "auth.session.revoked"


class FinanceEvents:
    # 交易
    TRANSACTION_CREATED = "finance.transaction.created"
    TRANSACTION_UPDATED = "finance.transaction.updated"
    TRANSACTION_DELETED = "finance.transaction.deleted"

    # 預算
    BUDGET_EXCEEDED = "finance.budget.exceeded"

    # 分類
    CATEGORY_CREATED = "finance.category.created"
    CATEGORY_UPDATED = "finance.category.updated"
    CATEGORY_DELETED = "finance.category.deleted"

    # 錢包
    WALLET_CREATED = "finance.wallet.created"
    WALLET_UPDATED = "finance.wallet.updated"
    WALLET_DELETED = "finance.wallet.deleted"
    WALLET_SYNCED = "finance.wallet.synced"
    WALLET_RECONCILED = "finance.wallet.reconciled"
    WALLET_CASH_GAP = "finance.wallet.cash_gap_detected"

    # 分期
    INSTALLMENT_CREATED = "finance.installment.created"
    INSTALLMENT_COMPLETED = "finance.installment.completed"
    INSTALLMENT_DUE = "finance.installment.due"
    INSTALLMENT_CANCELLED = "finance.installment.cancelled"

    # 轉帳
    TRANSFER_COMPLETED = "finance.transfer.completed"

    # 訂閱
    SUBSCRIPTION_RENEWED = "finance.subscription.renewed"

    # 快照
    GLOBAL_SNAPSHOT_CREATED = "finance.snapshot.global_created"

    # 隱密
    PRIVACY_TOGGLED = "finance.privacy.toggled"


class TaskflowEvents:
    TASK_CREATED = "taskflow.task.created"
    TASK_UPDATED = "taskflow.task.updated"
    TASK_COMPLETED = "taskflow.task.completed"
    TASK_STATUS_CHANGED = "taskflow.task.status_changed"
    TASK_DELETED = "taskflow.task.deleted"
    REPORT_GENERATED = "taskflow.report.generated"


class IdeagraphEvents:
    SPARK_CAPTURED = "ideagraph.spark.captured"
    SPARK_REFINED = "ideagraph.spark.refined"
    LINK_SUGGESTED = "ideagraph.link.suggested"
    LINK_VERIFIED = "ideagraph.link.verified"


class AdminEvents:
    HEALTH_CHECKED = "admin.health.checked"
    USER_MANAGED = "admin.user.managed"
    MODULE_TOGGLED = "admin.module.toggled"
    CONFIG_UPDATED = "admin.config.updated"
    # Audit trail
    ENTITY_SOFT_DELETED = "admin.entity.soft_deleted"
    ENTITY_RESTORED = "admin.entity.restored"
    ENTITY_PURGED = "admin.entity.purged"


class BriefingEvents:
    DAILY_COMPLETED = "briefing.daily.completed"
    DAILY_FAILED = "briefing.daily.failed"
    FOLLOW_UP_ASKED = "briefing.follow_up.asked"
    FOLLOW_UP_ANSWERED = "briefing.follow_up.answered"
    ANALYST_CREATED = "briefing.analyst.created"
    TOPIC_UPDATED = "briefing.topic.updated"


class IntelflowEvents:
    REPORT_CREATED = "intelflow.report.created"
    REPORT_UPDATED = "intelflow.report.updated"
    REPORT_DELETED = "intelflow.report.deleted"
    TOPIC_CREATED = "intelflow.topic.created"
    FEED_ADDED = "intelflow.feed.added"
    FEED_FETCHED = "intelflow.feed.fetched"


class MemvaultEvents:
    MEMORY_STORED = "memvault.memory.stored"
    MEMORY_UPDATED = "memvault.memory.updated"
    MEMORY_DELETED = "memvault.memory.deleted"
    MEMORY_RECALLED = "memvault.memory.recalled"
    MEMORY_PRUNED = "memvault.memory.pruned"
    EMBEDDING_COMPUTED = "memvault.embedding.computed"
    PROFILE_UPDATED = "memvault.profile.updated"
    # KG events
    TRIPLE_INGESTED = "memvault.triple.ingested"
    TRIPLE_BATCH_INGESTED = "memvault.triple.batch_ingested"
    COMMUNITY_REGENERATED = "memvault.community.regenerated"
    COMMUNITY_SUMMARY_REGENERATED = "memvault.community_summary.regenerated"
    ATTITUDE_EVOLVED = "memvault.attitude.evolved"
    SKILL_INVOKED = "memvault.skill.invoked"
    TRIPLE_INVALIDATED = "memvault.triple.invalidated"
    ENTITY_RESOLVED = "memvault.entity.resolved"
    ENTITY_MERGED = "memvault.entity.merged"
    REFLECTION_COMPLETED = "memvault.reflection.completed"
    KNOWLEDGE_CURATED = "memvault.knowledge.curated"


class SkillpathEvents:
    SKILL_UNLOCKED = "skillpath.skill.unlocked"
    PATH_PROGRESSED = "skillpath.path.progressed"
    MILESTONE_REACHED = "skillpath.milestone.reached"


class WorkpoolEvents:
    RESOURCE_ALLOCATED = "workpool.resource.allocated"
    RESOURCE_RELEASED = "workpool.resource.released"
    CAPACITY_EXCEEDED = "workpool.capacity.exceeded"


class MatchcoreEvents:
    MATCH_REQUESTED = "matchcore.match.requested"
    MATCH_FOUND = "matchcore.match.found"
    SCORE_CALCULATED = "matchcore.score.calculated"


class InvestEvents:
    TRADE_EXECUTED = "invest.trade.executed"
    DIVIDEND_RECEIVED = "invest.dividend.received"
    VALUATION_UPDATED = "invest.valuation.updated"
    POSITION_OPENED = "invest.position.opened"
    POSITION_CLOSED = "invest.position.closed"
    ACCOUNT_CREATED = "invest.account.created"
    ACCOUNT_UPDATED = "invest.account.updated"


class NodeflowEvents:
    FLOW_CREATED = "nodeflow.flow.created"
    FLOW_UPDATED = "nodeflow.flow.updated"
    FLOW_ACTIVATED = "nodeflow.flow.activated"
    FLOW_PAUSED = "nodeflow.flow.paused"
    FLOW_ARCHIVED = "nodeflow.flow.archived"
    FLOW_RUN_STARTED = "nodeflow.flow_run.started"
    FLOW_RUN_COMPLETED = "nodeflow.flow_run.completed"
    FLOW_RUN_FAILED = "nodeflow.flow_run.failed"
    NODE_EXECUTED = "nodeflow.node.executed"
    NODE_FAILED = "nodeflow.node.failed"


class NotificationEvents:
    PUSH_DELIVERED = "notification.push.delivered"
    PUSH_FAILED = "notification.push.failed"
    SUBSCRIPTION_CREATED = "notification.subscription.created"
    SUBSCRIPTION_REMOVED = "notification.subscription.removed"


class PluginEvents:
    INSTALLED = "plugin.installed"
    ENABLED = "plugin.enabled"
    DISABLED = "plugin.disabled"
    HOOK_TRIGGERED = "plugin.hook.triggered"


class CaptureEvents:
    CREATED = "capture.created"
    ENRICHED = "capture.enriched"
    PROMOTED = "capture.promoted"
    EXPIRED = "capture.expired"


class DailyosEvents:
    METHOD_CREATED = "dailyos.method.created"
    METHOD_UPDATED = "dailyos.method.updated"
    METHOD_DELETED = "dailyos.method.deleted"
    METHOD_SWITCHED = "dailyos.method.switched"
    PLAN_CREATED = "dailyos.plan.created"
    PLAN_UPDATED = "dailyos.plan.updated"
    PLAN_COMPLETED = "dailyos.plan.completed"
    REVIEW_SUBMITTED = "dailyos.review.submitted"


class SearchIndexEvents:
    """Events for Qdrant search index lifecycle."""

    INDEX_STARTED = "search.index.started"
    INDEX_COMPLETED = "search.index.completed"
    INDEX_FAILED = "search.index.failed"
    BACKFILL_STARTED = "search.backfill.started"
    BACKFILL_COMPLETED = "search.backfill.completed"


class SessionIntelligenceEvents:
    """Events from session-intelligence station → Core EventBus."""

    DIGEST_COMPLETED = "intelligence.digest.completed"
    PATTERN_DISCOVERED = "intelligence.pattern.discovered"
    TREND_DETECTED = "intelligence.trend.detected"


class PaperEvents:
    ARTICLE_CREATED = "paper.article.created"
    ARTICLE_UPDATED = "paper.article.updated"
    ARTICLE_DELETED = "paper.article.deleted"
    DIGEST_GENERATED = "paper.digest.generated"
    ANNOTATION_CREATED = "paper.annotation.created"


class SystemEvents:
    HEALTH_CHECKED = "system.health.checked"
    CONFIG_CHANGED = "system.config.changed"


class CompletionEvents:
    """Task completion signals from all execution tiers."""

    TASK_DISPATCHED = "completion.task.dispatched"
    TASK_RUNNING = "completion.task.running"
    TASK_COMPLETED = "completion.task.completed"
    TASK_FAILED = "completion.task.failed"
    TASK_TIMEOUT = "completion.task.timeout"
