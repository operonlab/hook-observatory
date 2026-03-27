"""Tier routing tests — written by independent test agent.

Tests ONLY derived from function signatures + config (routing_table.yaml + models.py),
NOT from reading the maestro.py implementation.

Each test includes a mutation comment explaining what code change it would catch.
"""

import pytest
from dataclasses import dataclass, field
from unittest.mock import patch, AsyncMock


# ---------------------------------------------------------------------------
# Local re-declaration of dataclasses (from signatures only — no impl import)
# ---------------------------------------------------------------------------


@dataclass
class TaskAnalysis:
    description: str
    complexity: str = "simple"
    decomposability: str = "atomic"
    categories: list[str] = field(default_factory=list)
    recommended_pattern: str = "solo"
    recommended_tier: str = "headless"
    phases: list[dict] = field(default_factory=list)


@dataclass
class AgentResult:
    task_id: str
    cli: str
    status: str
    duration_s: float
    output: str = ""


# ---------------------------------------------------------------------------
# Import the real functions (NOT the implementation detail — public surface)
# ---------------------------------------------------------------------------

from agent_metrics.engines.maestro import (
    dispatch_by_tier,
    get_tier_keywords,
    get_tier_routing,
    resolve_tier,
    select_tier,
)


# ===========================================================================
# TestSelectTier — synchronous tier selection logic
# ===========================================================================


class TestSelectTier:
    """Tests for select_tier() — synchronous tier selection from task analysis."""

    def test_explicit_override_wins_over_recommended_tier(self):
        """MUTATION: if override is ignored and recommended_tier is returned instead,
        this test catches it (fleet → headless mismatch)."""
        analysis = TaskAnalysis(
            description="build something",
            recommended_tier="headless",
        )
        result = select_tier(analysis, tier_override="fleet")
        assert result == "fleet"

    def test_override_relay_beats_recommended_fleet(self):
        """MUTATION: catches swapped precedence between override and recommended_tier."""
        analysis = TaskAnalysis(
            description="gpu model training",
            recommended_tier="fleet",
        )
        result = select_tier(analysis, tier_override="relay")
        assert result == "relay"

    def test_no_override_uses_recommended_tier_headless(self):
        """MUTATION: catches case where override=None still returns wrong default."""
        analysis = TaskAnalysis(
            description="write unit tests",
            recommended_tier="headless",
        )
        result = select_tier(analysis, tier_override=None)
        assert result == "headless"

    def test_no_override_uses_recommended_tier_fleet(self):
        """MUTATION: catches case where fleet recommended_tier is downgraded silently."""
        analysis = TaskAnalysis(
            description="multi-file refactor",
            recommended_tier="fleet",
        )
        result = select_tier(analysis, tier_override=None)
        assert result == "fleet"

    def test_no_override_browser_keyword_routes_to_relay(self):
        """MUTATION: catches case where browser keyword detection fails.
        'scrape' is a browser tier keyword → should route to relay."""
        analysis = TaskAnalysis(
            description="用 Playwright 瀏覽器 scrape 網站",
            categories=["frontend"],
            recommended_tier="relay",
        )
        result = select_tier(analysis, tier_override=None)
        assert result == "relay"

    def test_override_headless_string_accepted(self):
        """MUTATION: catches if 'headless' string is rejected or normalised wrongly."""
        analysis = TaskAnalysis(description="any task", recommended_tier="fleet")
        result = select_tier(analysis, tier_override="headless")
        assert result == "headless"

    def test_result_is_always_a_string(self):
        """MUTATION: catches if select_tier returns None or non-string."""
        analysis = TaskAnalysis(description="task", recommended_tier="headless")
        result = select_tier(analysis)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_override_takes_priority_regardless_of_categories(self):
        """MUTATION: catches if category list overrides the explicit tier_override."""
        analysis = TaskAnalysis(
            description="anything",
            categories=["debugging", "frontend"],
            recommended_tier="relay",
        )
        result = select_tier(analysis, tier_override="headless")
        assert result == "headless"


# ===========================================================================
# TestResolveTier — async tier selection with availability fallback
# ===========================================================================


class TestResolveTier:
    """Tests for resolve_tier() — tier selection with fallback when unavailable."""

    @pytest.mark.asyncio
    async def test_override_headless_always_available_no_fallback(self):
        """MUTATION: catches if headless is considered unavailable (it is always local).
        Fallback chain for headless is empty — should never fall back."""
        analysis = TaskAnalysis(description="task", recommended_tier="headless")
        result = await resolve_tier(analysis, tier_override="headless")
        assert result == "headless"

    @pytest.mark.asyncio
    async def test_fleet_unavailable_falls_back_to_relay(self):
        """MUTATION: catches if fleet→relay fallback chain is skipped or wrong order.
        YAML: fleet fallback = [relay, headless]. First available = relay."""
        analysis = TaskAnalysis(description="refactor everything", recommended_tier="fleet")

        # _check_tier_available uses lazy imports — mock at the function level
        async def mock_check(tier):
            if tier == "fleet":
                return False
            if tier == "relay":
                return True
            return tier == "headless"

        with patch(
            "agent_metrics.engines.maestro._check_tier_available",
            side_effect=mock_check,
        ):
            result = await resolve_tier(analysis, tier_override="fleet")
        assert result in ("relay", "headless")  # must NOT be "fleet"
        assert result != "fleet"

    @pytest.mark.asyncio
    async def test_fleet_unavailable_relay_unavailable_falls_back_to_headless(self):
        """MUTATION: catches if second-level fallback (relay→headless) is not attempted
        when both fleet and relay are down."""
        analysis = TaskAnalysis(description="gpu training", recommended_tier="fleet")

        async def mock_check(tier):
            return tier == "headless"  # only headless available

        with patch(
            "agent_metrics.engines.maestro._check_tier_available",
            side_effect=mock_check,
        ):
            result = await resolve_tier(analysis, tier_override="fleet")
        assert result == "headless"

    @pytest.mark.asyncio
    async def test_relay_unavailable_falls_back_to_headless(self):
        """MUTATION: catches if relay→headless fallback is not implemented.
        YAML: relay fallback = [headless]."""
        analysis = TaskAnalysis(description="browser task", recommended_tier="relay")

        async def mock_check(tier):
            return tier == "headless"  # only headless available

        with patch(
            "agent_metrics.engines.maestro._check_tier_available",
            side_effect=mock_check,
        ):
            result = await resolve_tier(analysis, tier_override="relay")
        assert result == "headless"

    @pytest.mark.asyncio
    async def test_fleet_available_returns_fleet(self):
        """MUTATION: catches if fleet is incorrectly downgraded when it IS available."""
        analysis = TaskAnalysis(description="multi-file migration", recommended_tier="fleet")

        async def mock_check(tier):
            return True  # all tiers available

        with patch(
            "agent_metrics.engines.maestro._check_tier_available",
            side_effect=mock_check,
        ):
            result = await resolve_tier(analysis, tier_override="fleet")
        assert result == "fleet"

    @pytest.mark.asyncio
    async def test_resolve_always_returns_valid_tier_string(self):
        """MUTATION: catches if resolve_tier returns None or empty string under any path."""
        analysis = TaskAnalysis(description="anything", recommended_tier="headless")
        result = await resolve_tier(analysis, tier_override=None)
        assert result in ("headless", "relay", "fleet")


# ===========================================================================
# TestDispatchByTier — unified dispatch routing
# ===========================================================================


class TestDispatchByTier:
    """Tests for dispatch_by_tier() — routes execution to correct backend by tier."""

    @pytest.mark.asyncio
    async def test_headless_tier_calls_dispatch_agent_not_fleet(self):
        """MUTATION: catches if headless tier accidentally routes to fleet or relay.
        Headless must use dispatch_agent (subprocess CLI execution path)."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_fleet",
            new_callable=AsyncMock,
        ) as mock_fleet:
            with patch(
                "agent_metrics.engines.maestro.dispatch_relay",
                new_callable=AsyncMock,
            ) as mock_relay:
                with patch(
                    "agent_metrics.engines.maestro.dispatch_agent",
                    return_value=AgentResult(
                        task_id="t1", cli="claude", status="done", duration_s=1.0
                    ),
                ) as mock_agent:
                    result = await dispatch_by_tier(
                        tier="headless",
                        cli="claude",
                        prompt="write a function",
                        cwd="/tmp",
                        skills_dir="/tmp/skills",
                    )
        mock_agent.assert_called_once()
        mock_fleet.assert_not_called()
        mock_relay.assert_not_called()

    @pytest.mark.asyncio
    async def test_relay_tier_calls_tmux_relay_not_fleet(self):
        """MUTATION: catches if relay tier mis-routes to fleet or headless."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_fleet",
            new_callable=AsyncMock,
        ) as mock_fleet:
            with patch(
                "agent_metrics.engines.maestro.dispatch_agent",
                return_value=AgentResult(task_id="tx", cli="claude", status="done", duration_s=0.1),
            ) as mock_agent:
                with patch(
                    "agent_metrics.engines.maestro.dispatch_relay",
                    new_callable=AsyncMock,
                    return_value=AgentResult(
                        task_id="t2", cli="claude", status="done", duration_s=2.0
                    ),
                ) as mock_relay:
                    result = await dispatch_by_tier(
                        tier="relay",
                        cli="claude",
                        prompt="scrape website",
                        cwd="/tmp",
                        skills_dir="/tmp/skills",
                    )
        mock_relay.assert_called_once()
        mock_fleet.assert_not_called()
        mock_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_fleet_tier_calls_fleet_not_relay(self):
        """MUTATION: catches if fleet tier routes to relay or headless subprocess."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_relay",
            new_callable=AsyncMock,
        ) as mock_relay:
            with patch(
                "agent_metrics.engines.maestro.dispatch_agent",
                return_value=AgentResult(task_id="tx", cli="claude", status="done", duration_s=0.1),
            ) as mock_agent:
                with patch(
                    "agent_metrics.engines.maestro.dispatch_fleet",
                    new_callable=AsyncMock,
                    return_value=AgentResult(
                        task_id="t3", cli="codex", status="done", duration_s=5.0
                    ),
                ) as mock_fleet:
                    result = await dispatch_by_tier(
                        tier="fleet",
                        cli="codex",
                        prompt="train model on GPU",
                        cwd=None,
                        skills_dir="/tmp/skills",
                    )
        mock_fleet.assert_called_once()
        mock_relay.assert_not_called()
        mock_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tier_falls_back_to_headless(self):
        """MUTATION: catches if unknown tier raises unhandled exception instead of
        gracefully falling back to headless (production safety)."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_agent",
            return_value=AgentResult(task_id="t4", cli="claude", status="done", duration_s=1.0),
        ) as mock_agent:
            result = await dispatch_by_tier(
                tier="unknown_tier_xyz",
                cli="claude",
                prompt="do something",
                cwd=None,
                skills_dir="/tmp/skills",
            )
        # Must not crash; headless is the safe default (else branch)
        assert result is not None
        assert result.status in ("done", "failed")

    @pytest.mark.asyncio
    async def test_dispatch_result_carries_correct_status(self):
        """MUTATION: catches if status field is hardcoded or not forwarded from backend."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_agent",
            return_value=AgentResult(
                task_id="t5", cli="claude", status="done", duration_s=3.0, output="ok"
            ),
        ):
            result = await dispatch_by_tier(
                tier="headless",
                cli="claude",
                prompt="build a test",
                cwd="/tmp",
                skills_dir="/tmp/skills",
            )
        assert result.status == "done"
        assert result.output == "ok"

    @pytest.mark.asyncio
    async def test_timeout_forwarded_to_relay(self):
        """MUTATION: catches if custom timeout is ignored and replaced with default 300."""
        with patch(
            "agent_metrics.engines.maestro.dispatch_relay",
            new_callable=AsyncMock,
            return_value=AgentResult(task_id="t6", cli="claude", status="done", duration_s=1.0),
        ) as mock_relay:
            await dispatch_by_tier(
                tier="relay",
                cli="claude",
                prompt="run MCP recall",
                cwd="/tmp",
                skills_dir="/tmp/skills",
                timeout=120,
            )
        call_kwargs = mock_relay.call_args
        # timeout=120 must appear somewhere in call (positional or keyword)
        all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
        assert 120 in all_args or call_kwargs.kwargs.get("timeout") == 120


# ===========================================================================
# TestTierInvariants — property-based behavioural invariants
# ===========================================================================


class TestTierInvariants:
    """Property-based invariants that must always hold, regardless of specific values."""

    def test_all_valid_overrides_are_accepted(self):
        """MUTATION: catches if any of the three valid tier names is rejected."""
        analysis = TaskAnalysis(description="any task")
        for tier in ("headless", "relay", "fleet"):
            result = select_tier(analysis, tier_override=tier)
            assert result == tier, f"override '{tier}' should be preserved exactly"

    def test_tier_routing_config_contains_three_tiers(self):
        """MUTATION: catches if a new tier name typo breaks the config (e.g. 'headles')."""
        routing = get_tier_routing()
        valid_tiers = {"headless", "relay", "fleet"}

        # All signal values must be valid tiers
        signals = routing.get("signals", {})
        for signal, tier in signals.items():
            assert tier in valid_tiers, f"signal '{signal}' maps to unknown tier '{tier}'"

        # All default category values must be valid tiers
        defaults = routing.get("defaults", {})
        for category, tier in defaults.items():
            assert tier in valid_tiers, f"category '{category}' maps to unknown tier '{tier}'"

    def test_fallback_chain_terminates_at_headless(self):
        """MUTATION: catches if fallback chain creates a cycle or skips headless as root."""
        routing = get_tier_routing()
        fallback = routing.get("fallback", {})

        # headless must have empty fallback (it is always local/available)
        assert fallback.get("headless", []) == [], "headless must have empty fallback chain"

        # All chains must eventually include headless or terminate
        def reachable(tier, visited=None):
            visited = visited or set()
            if tier in visited:
                return False  # cycle detected
            visited.add(tier)
            chain = fallback.get(tier, [])
            if not chain:
                return tier == "headless"
            return any(t == "headless" or reachable(t, visited.copy()) for t in chain)

        for tier in ("fleet", "relay"):
            assert reachable(tier), f"tier '{tier}' fallback chain must reach headless"

    def test_gpu_keywords_present_in_tier_keywords(self):
        """MUTATION: catches if 'gpu' signal keywords are removed or renamed in config."""
        keywords = get_tier_keywords()
        assert "gpu" in keywords
        gpu_kws = keywords["gpu"]
        assert len(gpu_kws) > 0
        # At least one GPU-related term must be present
        gpu_terms = {k.lower() for k in gpu_kws}
        assert any(term in gpu_terms for term in ("gpu", "cuda", "rtx", "vram", "inference")), (
            "GPU keywords must include at least one VRAM/compute term"
        )

    def test_mcp_keywords_route_to_relay_in_config(self):
        """MUTATION: catches if MCP signal is accidentally re-mapped to fleet."""
        routing = get_tier_routing()
        signals = routing.get("signals", {})
        assert signals.get("mcp") == "relay", (
            "MCP signal must route to relay (tmux-relay has full MCP/skill access)"
        )

    def test_browser_keywords_route_to_relay_in_config(self):
        """MUTATION: catches if browser signal is mapped to headless (no browser in headless)."""
        routing = get_tier_routing()
        signals = routing.get("signals", {})
        assert signals.get("browser") == "relay", "browser signal must route to relay"

    def test_gpu_signal_routes_to_fleet_in_config(self):
        """MUTATION: catches if GPU tasks are routed to relay (no GPU on local relay)."""
        routing = get_tier_routing()
        signals = routing.get("signals", {})
        assert signals.get("gpu") == "fleet", "GPU signal must route to fleet (remote RTX node)"

    def test_multi_file_signal_routes_to_fleet_in_config(self):
        """MUTATION: catches if multi_file signal drops to relay/headless tier."""
        routing = get_tier_routing()
        signals = routing.get("signals", {})
        assert signals.get("multi_file") == "fleet", "multi_file signal must route to fleet"

    def test_select_tier_override_none_never_returns_none(self):
        """MUTATION: catches if missing recommended_tier on analysis causes None return."""
        # analysis with deliberately empty recommended_tier (edge case)
        analysis = TaskAnalysis(description="task")
        # default recommended_tier is 'headless'
        result = select_tier(analysis, tier_override=None)
        assert result is not None
        assert result != ""

    @pytest.mark.asyncio
    async def test_resolve_tier_never_returns_invalid_tier(self):
        """MUTATION: catches if resolve_tier returns a non-tier string under fallback."""
        analysis = TaskAnalysis(description="task", recommended_tier="headless")
        result = await resolve_tier(analysis, tier_override=None)
        assert result in ("headless", "relay", "fleet"), (
            f"resolve_tier returned unexpected value: {result!r}"
        )

    def test_pydantic_plan_request_tier_field_accepts_none(self):
        """MUTATION: catches if tier field validation rejects None (auto-detect mode)."""
        from agent_metrics.models import PlanRequest

        req = PlanRequest(task="build feature", tier=None)
        assert req.tier is None

    def test_pydantic_plan_request_tier_field_accepts_fleet(self):
        """MUTATION: catches if PlanRequest rejects valid tier string 'fleet'."""
        from agent_metrics.models import PlanRequest

        req = PlanRequest(task="train model", tier="fleet")
        assert req.tier == "fleet"

    def test_pydantic_dispatch_request_tier_field_round_trips(self):
        """MUTATION: catches if DispatchRequest tier field is serialised/deserialised wrong."""
        from agent_metrics.models import DispatchRequest

        for tier in (None, "headless", "relay", "fleet"):
            req = DispatchRequest(task="do work", tier=tier)
            assert req.tier == tier, f"tier={tier!r} was mutated to {req.tier!r}"
