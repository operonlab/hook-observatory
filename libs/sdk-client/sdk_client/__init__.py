"""Workshop API clients.

Core modules (BaseClient, port 10000):
    from sdk_client.finance import FinanceClient
    from sdk_client.intelflow import IntelflowClient
    from sdk_client.nodeflow import NodeflowClient
    from sdk_client.memvault import MemvaultClient
    from sdk_client.notification import NotificationClient
    from sdk_client.auth import AuthClient
    from sdk_client.admin import AdminClient

Stations (standalone):
    from sdk_client.sentinel import SentinelClient
    from sdk_client.system_monitor import SystemMonitorClient
    from sdk_client.tmux_relay import TmuxRelayClient
    from sdk_client.tmux_webui import TmuxWebuiClient
    from sdk_client.agent_metrics import AgentMetricsClient
    from sdk_client.hook_observatory import HookObservatoryClient
    from sdk_client.session_channel import SessionChannelClient
    from sdk_client.sandbox import SandboxClient
    from sdk_client.remote_node import RemoteNodeClient

CLI wrappers (subprocess):
    from sdk_client.envkit import EnvkitClient
    from sdk_client.session_archiver import SessionArchiverClient

Direct impl (no HTTP server):
    from sdk_client.session_redactor import SessionRedactorClient
    from sdk_client.session_pipeline import SessionPipelineClient
    from sdk_client.session_intelligence import SessionIntelligenceClient
"""
