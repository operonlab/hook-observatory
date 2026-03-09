"""Browser Bridge CLI — Agent-as-your-hands terminal interface.

Commands:
    bridge chat <provider> <prompt>   Send a prompt via a provider
    bridge new <provider>             Start a new conversation
    bridge history <conv-id>          Show conversation message history
    bridge sessions                   List active browser sessions
    bridge providers                  List available providers
    bridge health                     Check service health
"""

from __future__ import annotations

import sys

import click

from workshop.clients.browser_bridge import (
    BrowserBridgeClient,
    BrowserBridgeError,
    BrowserBridgeConnectionError,
)


def _err(msg: str) -> None:
    click.echo(f"Error: {msg}", err=True)
    sys.exit(1)


def _handle(fn):
    """Decorator: catch BrowserBridge errors and exit cleanly."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BrowserBridgeConnectionError as e:
            _err(str(e))
        except BrowserBridgeError as e:
            _err(f"[{e.status_code}] {e.detail}")

    return wrapper


# ------------------------------------------------------------------ #
# CLI group                                                           #
# ------------------------------------------------------------------ #


@click.group()
@click.version_option(package_name="browser-bridge")
def main() -> None:
    """Browser Bridge — drive web AI services from the terminal."""


# ------------------------------------------------------------------ #
# bridge providers                                                    #
# ------------------------------------------------------------------ #


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def providers(as_json: bool) -> None:
    """List available browser providers."""
    with BrowserBridgeClient() as client:
        data = client.providers()

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    if not data:
        click.echo("No providers registered.")
        return

    click.echo(f"{'Name':<20} {'URL':<40} Description")
    click.echo("-" * 80)
    for p in data:
        name = p.get("name", p.get("id", "?"))
        url = p.get("base_url", p.get("url", ""))
        desc = p.get("description", "")
        click.echo(f"{name:<20} {url:<40} {desc}")


# ------------------------------------------------------------------ #
# bridge sessions                                                     #
# ------------------------------------------------------------------ #


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def sessions(as_json: bool) -> None:
    """List active browser sessions."""
    with BrowserBridgeClient() as client:
        data = client.sessions()

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    if not data:
        click.echo("No active sessions.")
        return

    click.echo(f"{'ID':<20} {'Provider':<15} {'Created':<28} Status")
    click.echo("-" * 80)
    for s in data:
        sid = s.get("id", "?")[:18]
        provider = s.get("provider", "?")
        created = s.get("created_at", "?")[:26]
        status = s.get("status", "?")
        click.echo(f"{sid:<20} {provider:<15} {created:<28} {status}")


# ------------------------------------------------------------------ #
# bridge new                                                          #
# ------------------------------------------------------------------ #


@main.command(name="new")
@click.argument("provider")
@click.option("--model", "-m", default=None, help="Model to use (provider default if omitted)")
@click.option("--system", "-s", default=None, help="System prompt")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def new_conversation(provider: str, model: str | None, system: str | None, as_json: bool) -> None:
    """Start a new conversation with PROVIDER."""
    with BrowserBridgeClient() as client:
        data = client.new_conversation(provider=provider, model=model, system_prompt=system)

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    conv_id = data.get("id", "?")
    click.echo(f"Conversation started.")
    click.echo(f"  ID:       {conv_id}")
    click.echo(f"  Provider: {data.get('provider', provider)}")
    if data.get("model"):
        click.echo(f"  Model:    {data['model']}")


# ------------------------------------------------------------------ #
# bridge chat                                                         #
# ------------------------------------------------------------------ #


@main.command()
@click.argument("provider")
@click.argument("prompt")
@click.option("--conv", "-c", default=None, help="Conversation ID to continue")
@click.option("--timeout", "-t", default=120.0, show_default=True, help="Seconds to wait")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def chat(
    provider: str,
    prompt: str,
    conv: str | None,
    timeout: float,
    as_json: bool,
) -> None:
    """Send PROMPT to PROVIDER and print the response.

    If --conv is given, continue that conversation.
    Otherwise a new conversation is created automatically.
    """
    with BrowserBridgeClient(timeout=timeout + 10) as client:
        # Auto-create conversation if no ID supplied
        if not conv:
            new = client.new_conversation(provider=provider)
            conv = new.get("id")
            if not conv:
                _err("Failed to create conversation (no ID returned)")

        data = client.chat(conversation_id=conv, message=prompt, timeout=timeout)

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    content = data.get("content") or data.get("response") or data.get("text") or ""
    if not content:
        _err(f"Empty response. Raw: {data}")

    click.echo(content)

    # Footer metadata
    latency = data.get("latency_ms") or data.get("elapsed")
    if latency:
        suffix = "ms" if data.get("latency_ms") else "s"
        click.echo(f"\n[conv: {conv}  elapsed: {latency}{suffix}]", err=True)


# ------------------------------------------------------------------ #
# bridge history                                                      #
# ------------------------------------------------------------------ #


@main.command()
@click.argument("conv_id")
@click.option("--limit", "-n", default=50, show_default=True, help="Max messages")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def history(conv_id: str, limit: int, as_json: bool) -> None:
    """Show message history for CONV_ID."""
    with BrowserBridgeClient() as client:
        data = client.history(conversation_id=conv_id, limit=limit)

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    if not data:
        click.echo("No messages found.")
        return

    for msg in data:
        role = msg.get("role", "?").upper()
        content = msg.get("content", "")
        ts = msg.get("timestamp", msg.get("created_at", ""))[:19]
        click.echo(f"[{ts}] {role}")
        click.echo(content)
        click.echo()


# ------------------------------------------------------------------ #
# bridge health                                                       #
# ------------------------------------------------------------------ #


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@_handle
def health(as_json: bool) -> None:
    """Check service health."""
    with BrowserBridgeClient() as client:
        data = client.health()

    if as_json:
        import json
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return

    status = data.get("status", "?")
    version = data.get("version", "?")
    providers_list = data.get("providers", [])
    active = data.get("active_sessions", 0)

    icon = "OK" if status == "ok" else "ERROR"
    click.echo(f"[{icon}] browser-bridge v{version}")
    click.echo(f"  Providers:       {', '.join(providers_list) or 'none'}")
    click.echo(f"  Active sessions: {active}")
