"""Event type constants — {domain}.{entity}.{past_tense}"""


class AuthEvents:
    USER_REGISTERED = "auth.user.registered"
    USER_LOGGED_IN = "auth.user.logged_in"
    USER_LOGGED_OUT = "auth.user.logged_out"
    USER_STATUS_CHANGED = "auth.user.status_changed"
    ROLE_ASSIGNED = "auth.role.assigned"


class FinanceEvents:
    TRANSACTION_CREATED = "finance.transaction.created"
    TRANSACTION_UPDATED = "finance.transaction.updated"
    BUDGET_EXCEEDED = "finance.budget.exceeded"
    SUBSCRIPTION_RENEWED = "finance.subscription.renewed"


class QuestEvents:
    QUEST_CREATED = "quest.quest.created"
    QUEST_ACCEPTED = "quest.quest.accepted"
    QUEST_COMPLETED = "quest.quest.completed"
    SKILL_UNLOCKED = "quest.skill.unlocked"


class MuseEvents:
    SPARK_CREATED = "muse.spark.created"
    LINK_FORMED = "muse.link.formed"


class PluginEvents:
    INSTALLED = "plugin.installed"
    ENABLED = "plugin.enabled"
    DISABLED = "plugin.disabled"
    HOOK_TRIGGERED = "plugin.hook.triggered"


class SystemEvents:
    HEALTH_CHECKED = "system.health.checked"
    CONFIG_CHANGED = "system.config.changed"
