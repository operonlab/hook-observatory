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

    # 錢包
    WALLET_SYNCED = "finance.wallet.synced"
    WALLET_RECONCILED = "finance.wallet.reconciled"

    # 分期
    INSTALLMENT_CREATED = "finance.installment.created"
    INSTALLMENT_COMPLETED = "finance.installment.completed"
    INSTALLMENT_DUE = "finance.installment.due"
    INSTALLMENT_CANCELLED = "finance.installment.cancelled"

    # 轉帳
    TRANSFER_COMPLETED = "finance.transfer.completed"

    # 訂閱
    SUBSCRIPTION_RENEWED = "finance.subscription.renewed"

    # 隱密
    PRIVACY_TOGGLED = "finance.privacy.toggled"


class TaskflowEvents:
    TASK_CREATED = "taskflow.task.created"
    TASK_ACCEPTED = "taskflow.task.accepted"
    TASK_COMPLETED = "taskflow.task.completed"
    TASK_BLOCKED = "taskflow.task.blocked"
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


class IntelflowEvents:
    REPORT_CREATED = "intelflow.report.created"
    REPORT_UPDATED = "intelflow.report.updated"
    REPORT_DELETED = "intelflow.report.deleted"
    TOPIC_CREATED = "intelflow.topic.created"
    FEED_ADDED = "intelflow.feed.added"
    FEED_FETCHED = "intelflow.feed.fetched"
    BRIEFING_GENERATED = "intelflow.briefing.generated"


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
    CLUSTER_REGENERATED = "memvault.cluster.regenerated"
    WISDOM_REGENERATED = "memvault.wisdom.regenerated"
    ATTITUDE_EVOLVED = "memvault.attitude.evolved"
    SKILL_INVOKED = "memvault.skill.invoked"


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


class PluginEvents:
    INSTALLED = "plugin.installed"
    ENABLED = "plugin.enabled"
    DISABLED = "plugin.disabled"
    HOOK_TRIGGERED = "plugin.hook.triggered"


class SystemEvents:
    HEALTH_CHECKED = "system.health.checked"
    CONFIG_CHANGED = "system.config.changed"
