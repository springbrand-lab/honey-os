"""Gateway-owned resolver for Builder activation cards.

This module is deliberately outside the model tool surface.  It turns already
authenticated transport facts into the fixed companion owner lane; callers do
not supply an ``authenticated`` flag or a claimed lane string.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

from honeyos.companion import builder_activation as _activation
from honeyos.gateway.config import Platform
from honeyos.gateway.platforms.base import MessageEvent
from honeyos.gateway.session import build_session_key


_OWNER_LANE = "agent:main:companion:dm:owner"


def _store(home: Path) -> _activation.ActivationStore:
    return _activation.ActivationStore(
        Path(home).expanduser().resolve(), Path(__file__).parents[2]
    )


def _make_gateway_resolvers():
    """Close over the unforgeable gateway capability.

    This intentionally leaves no module-level capability for a model-facing
    caller to pass around.  Only the two transport adapters below receive a
    resolver function; they derive identity from their authenticated session.
    """

    capability = _activation._GATEWAY_RESOLVER_CAPABILITY

    def resolve_local_web_callback(
        home: Path, callback_id: str, *, choice: str, now: datetime | None = None
    ) -> _activation.ActivationRecord:
        """Resolve an API-server card after its route authenticates the session."""

        return _store(home)._resolve_gateway_confirmation(
            callback_id,
            capability=capability,
            owner_lane=_OWNER_LANE,
            channel=Platform.API_SERVER.value,
            choice=choice,
            now=now,
        )

    def resolve_feishu_callback(
        home: Path, callback_id: str, *, choice: str, event: MessageEvent
    ) -> _activation.ActivationRecord:
        """Resolve a Feishu card from the adapter's verified DM MessageEvent."""

        source = event.source
        if (
            source is None
            or source.platform != Platform.FEISHU
            or source.chat_type != "dm"
            or build_session_key(source) != _OWNER_LANE
        ):
            raise _activation.ActivationConflict(
                "activation confirmation requires an authenticated owner callback"
            )
        return _store(home)._resolve_gateway_confirmation(
            callback_id,
            capability=capability,
            owner_lane=_OWNER_LANE,
            channel=Platform.FEISHU.value,
            choice=choice,
        )

    return resolve_local_web_callback, resolve_feishu_callback


resolve_local_web_callback, resolve_feishu_callback = _make_gateway_resolvers()
del _make_gateway_resolvers
