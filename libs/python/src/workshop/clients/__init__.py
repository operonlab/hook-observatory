"""Workshop API clients.

Core modules (BaseClient, port 8801):
    from workshop.clients.finance import FinanceClient
    from workshop.clients.intelflow import IntelflowClient
    from workshop.clients.nodeflow import NodeflowClient
    from workshop.clients.memvault import MemvaultClient
    from workshop.clients.notification import NotificationClient
    from workshop.clients.auth import AuthClient
    from workshop.clients.admin import AdminClient

Stations (standalone):
    from workshop.clients.sentinel import SentinelClient
    from workshop.clients.system_monitor import SystemMonitorClient
    from workshop.clients.tmux_relay import TmuxRelayClient
    from workshop.clients.tmux_webui import TmuxWebuiClient
    from workshop.clients.agent_metrics import AgentMetricsClient
    from workshop.clients.hook_observatory import HookObservatoryClient
    from workshop.clients.sandbox import SandboxClient

CLI wrappers (subprocess):
    from workshop.clients.envkit import EnvkitClient
    from workshop.clients.session_archiver import SessionArchiverClient
"""
