"""`RequestRouter` — agents phase-15 §1/§4: classify every inbound request
into `fast` (deterministic, zero LLM tokens), `slow` (full Bedrock Agent
reasoning), or `shadow` (both, in parallel, for divergence measurement).

The decision *tree* below is code (agents/README.md §1's "policy is data,
logic is code" split, same precedent as F6's `service_prefixes.py`); the
thresholds, keyword lists, and route -> target mapping it reads come from
`agents/data/router_policy.yaml`, hot-swappable in prod via SSM parameter
`/sentinel/router/policy` (§4: "Change without redeploying by SSM param
update") through `load_policy`'s optional `SsmParameterClient` -- when no
client is given (unit tests, or the SSM param has never been published)
`load_policy` falls back to the bundled YAML file, the same "clear degrade,
never a crash" precedent `SsmParameterClient` itself documents.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING

import yaml
from pydantic import Field

from iam_sentinel_agents.contracts.common import Base, FeatureID
from iam_sentinel_agents.contracts.routing import RoutingDecision

if TYPE_CHECKING:
    from collections.abc import Callable

    from iam_sentinel_adapters.ssm.params import SsmParameterClient

_POLICY_PATH = Path(__file__).resolve().parents[4] / "data" / "router_policy.yaml"
_SSM_POLICY_PARAM = "/sentinel/router/policy"

_EMERGENCY_API_PATH = "/emergency/kill-session"
_CHAT_API_PATH = "/agent/chat"


class FastPathRoute(Base):
    target: FeatureID
    required_fields: list[str] = Field(default_factory=list)


class RouterPolicy(Base):
    version: int
    fast_path_routes: dict[str, FastPathRoute]
    reasoning_keywords: list[str]
    narrative_hint_key: str
    multi_feature_threshold: int = Field(ge=1)
    shadow_sampling_rate: dict[str, float]
    high_severity_shadow_rate: float = Field(ge=0.0, le=1.0)
    router_change_window_days: int = Field(ge=0)


class RouterRequest(Base):
    """The router's own input shape -- deliberately broader than
    `FastPathRequest` (backend phase-01's `payload: dict[str, object]`
    passthrough): the backend REST routes already know which target they
    want (the URL path fixes it), so `RequestRouter.classify` is mainly
    exercised here by `/agent/chat`-shaped and shadow-sampled inputs; the
    `/analyze/*`-style routes hit rule R0's api_path lookup and resolve in
    one step.
    """

    correlation_id: str = Field(min_length=1, max_length=128)
    api_path: str = Field(min_length=1, max_length=128)
    query_text: str | None = None
    hints: dict[str, object] = Field(default_factory=dict)
    fields_present: list[str] = Field(default_factory=list)
    features_touched: list[FeatureID] = Field(default_factory=list)
    min_severity_hint: str | None = None


def _default_policy_dict() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8")))


def load_policy(*, ssm_client: SsmParameterClient | None = None) -> RouterPolicy:
    raw: dict[str, Any] | None = None
    if ssm_client is not None:
        published = ssm_client.get_parameter(_SSM_POLICY_PARAM)
        if published is not None:
            raw = yaml.safe_load(published)
    if raw is None:
        raw = _default_policy_dict()
    return RouterPolicy.model_validate(raw)


def _mentions_reasoning_keyword(query_text: str, keywords: list[str]) -> bool:
    lowered = query_text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


class RequestRouter:
    def __init__(
        self,
        policy: RouterPolicy | None = None,
        *,
        stage: str = "dev",
        rng: Any = None,
        is_within_change_window: bool = False,
    ) -> None:
        self._policy = policy or load_policy()
        self._stage = stage
        self._rng = rng or random.random
        self._is_within_change_window = is_within_change_window

    @property
    def policy(self) -> RouterPolicy:
        return self._policy

    def classify(self, request: RouterRequest) -> RoutingDecision:
        """§4's Router Policy Matrix, evaluated top-to-bottom as a decision
        tree: the first rule (`_RULE_CHECKS`, in matrix order) that matches
        wins. `_rule_default_slow` never returns `None`, so the loop always
        terminates -- it exists as a plain method only so `PLR0911` (max
        return statements) doesn't force one giant if/elif chain here.
        """
        for rule in self._RULE_CHECKS:
            decision = rule(self, request)
            if decision is not None:
                return decision
        return self._rule_default_slow(request)

    def _rule_emergency(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: emergency path is Fast+audit, unconditionally -- F5's
        # dispatcher is deterministic and must never wait on an LLM hop.
        if request.api_path != _EMERGENCY_API_PATH:
            return None
        return RoutingDecision(
            mode="fast",
            reason="emergency kill-session path is always deterministic (no LLM hot path)",
            dispatch_target="F5",
            matched_policy_rule_id="R0-emergency",
            correlation_id=request.correlation_id,
        )

    def _rule_narrative_hint(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: include_narrative=true forces Slow (narrative synthesis
        # needs the LLM even if the underlying computation is trivial).
        if not bool(request.hints.get(self._policy.narrative_hint_key)):
            return None
        return self._slow(request, rule_id="R1-narrative-hint", reason="hints.include_narrative=true")

    def _rule_reasoning_keyword(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: reasoning keywords force Slow regardless of structure.
        if not request.query_text or not _mentions_reasoning_keyword(
            request.query_text, self._policy.reasoning_keywords
        ):
            return None
        return self._slow(
            request,
            rule_id="R2-reasoning-keyword",
            reason="query_text mentions a reasoning keyword (why/explain/compare/recommend)",
        )

    def _rule_multi_feature(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: multi-feature queries need Prime's cross-specialist
        # synthesis, never a single deterministic mirror.
        if len(request.features_touched) < self._policy.multi_feature_threshold:
            return None
        return self._slow(
            request,
            rule_id="R3-multi-feature",
            reason=f"query touches {len(request.features_touched)} features (>= threshold)",
        )

    def _rule_agent_chat(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: /agent/chat with natural-language query_text -> Slow,
        # dispatched to Prime (the only route with no fixed feature target).
        if request.api_path != _CHAT_API_PATH or not request.query_text:
            return None
        return self._slow(
            request, rule_id="R4-agent-chat", reason="/agent/chat carries free-text query_text"
        )

    def _rule_structured_fast_path(self, request: RouterRequest) -> RoutingDecision | None:
        # §4 row: a structured, path-matched, query_text-free payload with
        # every required field present is Fast.
        route = self._policy.fast_path_routes.get(request.api_path)
        if (
            route is None
            or request.query_text
            or not set(route.required_fields) <= set(request.fields_present)
        ):
            return None
        decision = RoutingDecision(
            mode="fast",
            reason=f"{request.api_path} matched with a complete structured payload",
            dispatch_target=route.target,
            matched_policy_rule_id="R5-structured-fast-path",
            correlation_id=request.correlation_id,
        )
        return self._maybe_upgrade_to_shadow(request, decision)

    def _rule_default_slow(self, request: RouterRequest) -> RoutingDecision:
        # No rule matched a Fast route: ambiguity resolution is the LLM's
        # job (§3's "Slow... used when the answer requires interpretation,
        # ambiguity resolution, or narrative synthesis"), and defaulting to
        # Slow is the safe direction to fail in.
        return self._slow(
            request, rule_id="R6-default-slow", reason="no fast-path rule matched; ambiguous input"
        )

    _RULE_CHECKS: tuple[Callable[[RequestRouter, RouterRequest], RoutingDecision | None], ...] = (
        _rule_emergency,
        _rule_narrative_hint,
        _rule_reasoning_keyword,
        _rule_multi_feature,
        _rule_agent_chat,
        _rule_structured_fast_path,
    )

    def _slow(self, request: RouterRequest, *, rule_id: str, reason: str) -> RoutingDecision:
        dispatch_target = "prime"
        return RoutingDecision(
            mode="slow",
            reason=reason,
            dispatch_target=dispatch_target,
            matched_policy_rule_id=rule_id,
            correlation_id=request.correlation_id,
        )

    def _maybe_upgrade_to_shadow(
        self, request: RouterRequest, decision: RoutingDecision
    ) -> RoutingDecision:
        """§4 row: "Shadow sampling coin-flip fires -> Shadow", overlaid on
        top of an otherwise-Fast decision (§3: shadow always runs *both*
        paths, so it only ever supersedes a Fast verdict, never a Slow
        one -- Slow already gets the full reasoning path on its own).
        §10 risk mitigation: HIGH+ severity hints get shadow-verified at
        100% for `router_change_window_days` after a policy change.
        """
        rate = self._policy.shadow_sampling_rate.get(self._stage, 1.0)
        if (
            self._is_within_change_window
            and request.min_severity_hint in ("HIGH", "CRITICAL")
        ):
            rate = self._policy.high_severity_shadow_rate
        if self._rng() >= rate:
            return decision
        return RoutingDecision(
            mode="shadow",
            reason=f"{decision.reason}; shadow sampling fired at rate={rate}",
            dispatch_target=decision.dispatch_target,
            matched_policy_rule_id="R7-shadow-sample",
            fallback_target=decision.dispatch_target,
            correlation_id=request.correlation_id,
        )
