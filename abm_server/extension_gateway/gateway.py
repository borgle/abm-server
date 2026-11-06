from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ..config import Settings
from ..database import Database
from ..quotas import quota_policy
from .protocol import (
    SessionError,
    envelope,
    error_envelope,
)

logger = logging.getLogger(__name__)


class GatewayCallError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        action: str = "none",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.action = action


@dataclass(slots=True)
class GatewayPeer:
    websocket: WebSocket
    api_key_id: str
    user_id: str
    extension_id: str
    extension_version: str
    connected_at: datetime
    last_seen: datetime
    connection_id: str = ""
    browser_id: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = True

    def __post_init__(self) -> None:
        if not self.connection_id:
            self.connection_id = self.api_key_id

    async def send(self, message: dict[str, Any]) -> bool:
        if not self.active or self.websocket.client_state != WebSocketState.CONNECTED:
            return False
        async with self.send_lock:
            try:
                await self.websocket.send_json(message)
                return True
            except Exception:
                logger.warning("Failed to send WebSocket message", exc_info=True)
                return False


@dataclass(slots=True)
class PendingCall:
    api_key_id: str
    connection_id: str
    tool_name: str
    future: asyncio.Future[dict[str, Any]]
    started_at: datetime


@dataclass(slots=True)
class ConnectionLease:
    user_id: str
    session_id: str
    api_key_id: str
    connection_id: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    group_title: str | None = None
    collapsed: bool | None = None
    priority: int = 0


class ExtensionGateway:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self._connections: dict[str, GatewayPeer] = {}
        self._key_connections: dict[str, set[str]] = {}
        self._pending: dict[str, PendingCall] = {}
        self._leases: dict[tuple[str, str], ConnectionLease] = {}
        self._lease_owners: dict[str, tuple[str, str]] = {}
        self._lease_cursor: dict[str, int] = {}
        self._browser_limit_cache: dict[str, tuple[float, tuple[int, int, int]]] = {}
        self._quota_policy = quota_policy(settings)
        self._state_lock = asyncio.Lock()

    @staticmethod
    def connection_id_for(api_key_id: str, browser_id: str | None) -> str:
        if not browser_id:
            return api_key_id
        digest = hashlib.sha256(f"{api_key_id}:{browser_id}".encode()).hexdigest()[:24]
        return f"conn_{digest}"

    async def _browser_limits(self, user_id: str) -> tuple[int, int, int]:
        now = time.monotonic()
        cached = self._browser_limit_cache.get(user_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        if self.database is None:
            values = (
                self.settings.extension_max_connections_per_key,
                self.settings.extension_max_sessions_per_connection,
                self.settings.extension_reserved_priority_slots,
            )
        else:
            async with self.database.sessions() as session:
                values = await self._quota_policy.browser_limits(session, user_id)
        self._browser_limit_cache[user_id] = (now + 30.0, values)
        return values

    async def register(self, peer: GatewayPeer) -> GatewayPeer | None:
        """Register one browser instance.

        A browser that sends a stable ``browser_id`` gets its own
        ``connection_id``; several browsers may share one API Key. Legacy
        extensions that only send an API Key keep the previous single-connection
        behaviour and replace each other.
        """
        max_connections, _, _ = await self._browser_limits(peer.user_id)
        async with self._state_lock:
            if peer.browser_id:
                key_ids = self._key_connections.setdefault(peer.api_key_id, set())
                if peer.connection_id not in key_ids and len(key_ids) >= max_connections:
                    raise GatewayCallError(
                        "ABM_CONNECTION_LIMIT",
                        "This API Key reached its browser connection limit.",
                        retryable=False,
                        action="revoke_connection",
                    )
                previous = self._connections.get(peer.connection_id)
                if previous is not None and previous is not peer:
                    self._release_connection_leases(peer.connection_id)
                self._connections[peer.connection_id] = peer
                key_ids.add(peer.connection_id)
            else:
                previous = self._connections.get(peer.api_key_id)
                if previous is not None and previous is not peer:
                    self._release_key_leases(peer.api_key_id)
                self._connections[peer.connection_id] = peer
                self._key_connections.setdefault(peer.api_key_id, set()).clear()
                self._key_connections[peer.api_key_id].add(peer.connection_id)
        if previous is not None and previous is not peer:
            await self.close_peer(
                previous,
                SessionError(
                    "ABM_CONNECTION_REPLACED",
                    "A new connection was established for the same browser or API Key.",
                    1000,
                ),
            )
        return previous

    async def unregister(self, peer: GatewayPeer) -> None:
        async with self._state_lock:
            if self._connections.get(peer.connection_id) is peer:
                self._connections.pop(peer.connection_id, None)
                key_ids = self._key_connections.get(peer.api_key_id)
                if key_ids is not None:
                    key_ids.discard(peer.connection_id)
                    if not key_ids:
                        self._key_connections.pop(peer.api_key_id, None)
                self._release_connection_leases(peer.connection_id)
        peer.active = False
        await self.reject_pending_for_connection(
            peer.connection_id,
            GatewayCallError(
                "ABM_EXTENSION_OFFLINE",
                "Extension connection closed.",
                retryable=True,
                action="wait",
            ),
        )

    def get_peer(self, identifier: str) -> GatewayPeer | None:
        """Resolve a connection id, with an API key fallback for legacy callers."""
        peer = self._connections.get(identifier)
        if peer is not None:
            return peer
        for connection_id in self._key_connections.get(identifier, ()):
            candidate = self._connections.get(connection_id)
            if candidate is not None and candidate.active:
                return candidate
        return None

    def connections_for_user(self, user_id: str) -> list[GatewayPeer]:
        return [
            peer for peer in self._connections.values() if peer.user_id == user_id and peer.active
        ]

    def api_key_for_connection(self, connection_id: str) -> str | None:
        peer = self._connections.get(connection_id)
        return peer.api_key_id if peer is not None else None

    def connected_key_for_user(
        self,
        user_id: str,
        allowed_api_key_ids: set[str] | None = None,
    ) -> str | None:
        """Return the API Key of the most recently active connection for a user."""
        candidates = [
            (peer.last_seen, peer.api_key_id)
            for peer in self._connections.values()
            if peer.user_id == user_id
            and peer.active
            and (allowed_api_key_ids is None or peer.api_key_id in allowed_api_key_ids)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _remove_lease(self, key: tuple[str, str]) -> None:
        lease = self._leases.pop(key, None)
        if lease is not None and self._lease_owners.get(lease.connection_id) == key:
            self._lease_owners.pop(lease.connection_id, None)

    def _release_key_leases(self, api_key_id: str) -> None:
        for key, lease in list(self._leases.items()):
            if lease.api_key_id == api_key_id:
                self._remove_lease(key)

    def _release_connection_leases(self, connection_id: str) -> None:
        for key, lease in list(self._leases.items()):
            if lease.connection_id == connection_id:
                self._remove_lease(key)

    def _purge_expired_leases(self, now: datetime) -> None:
        expired = [key for key, lease in self._leases.items() if lease.expires_at <= now]
        for key in expired:
            self._remove_lease(key)

    def lease_for_session(self, user_id: str, session_id: str) -> str | None:
        lease = self._leases.get((user_id, session_id))
        if lease is None or lease.expires_at <= datetime.now(UTC):
            return None
        peer = self._connections.get(lease.connection_id)
        if peer is None or not peer.active:
            return None
        return lease.connection_id

    async def touch_session(
        self,
        user_id: str,
        session_id: str,
        ttl_seconds: int | None = None,
    ) -> str | None:
        """Validate and renew a browser/MCP session lease."""
        now = datetime.now(UTC)
        ttl = self.settings.mcp_session_lease_ttl_seconds if ttl_seconds is None else ttl_seconds
        ttl = max(1, ttl)
        key = (user_id, session_id)
        async with self._state_lock:
            lease = self._leases.get(key)
            if lease is None or lease.expires_at <= now:
                self._remove_lease(key)
                return None
            peer = self._connections.get(lease.connection_id)
            if peer is None or not peer.active:
                self._remove_lease(key)
                return None
            lease.last_used_at = now
            lease.expires_at = now + timedelta(seconds=ttl)
            return lease.connection_id

    def session_context(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        lease = self._leases.get((user_id, session_id))
        if lease is None:
            return None
        return {
            "taskId": lease.session_id,
            "connectionId": lease.connection_id,
            "groupTitle": lease.group_title,
            "collapsed": lease.collapsed,
            "priority": lease.priority,
        }

    async def release_session(self, user_id: str, session_id: str) -> None:
        """Release the connection lease owned by one MCP session."""
        async with self._state_lock:
            self._remove_lease((user_id, session_id))

    def _session_count(self, connection_id: str) -> int:
        return sum(1 for lease in self._leases.values() if lease.connection_id == connection_id)

    async def acquire_connection_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
        preferred_api_key_id: str | None = None,
        allowed_api_key_ids: set[str] | None = None,
        preferred_connection_id: str | None = None,
        allowed_connection_ids: set[str] | None = None,
        ttl_seconds: int | None = None,
        group_title: str | None = None,
        collapsed: bool | None = None,
        priority: int = 0,
    ) -> str:
        """Lease one browser connection for a task session.

        Multiple browsers may share an API Key. Every connection still serves
        one task session at a time; per-connection tab groups arrive in the next
        phase. Callers may prefer/allow specific connection or key ids.
        """
        now = datetime.now(UTC)
        ttl = self.settings.mcp_session_lease_ttl_seconds if ttl_seconds is None else ttl_seconds
        ttl = max(1, ttl)
        key = (user_id, session_id)
        _, session_limit, reserved_limit = await self._browser_limits(user_id)

        async with self._state_lock:
            self._purge_expired_leases(now)
            online = {
                connection_id: peer
                for connection_id, peer in self._connections.items()
                if peer.user_id == user_id
                and peer.active
                and (allowed_api_key_ids is None or peer.api_key_id in allowed_api_key_ids)
                and (allowed_connection_ids is None or connection_id in allowed_connection_ids)
            }

            existing = self._leases.get(key)
            if existing is not None:
                if (
                    existing.connection_id not in online
                    or (
                        preferred_connection_id is not None
                        and existing.connection_id != preferred_connection_id
                    )
                    or (
                        preferred_api_key_id is not None
                        and existing.api_key_id != preferred_api_key_id
                    )
                ):
                    self._remove_lease(key)
                else:
                    existing.last_used_at = now
                    existing.expires_at = now + timedelta(seconds=ttl)
                    return existing.connection_id

            if preferred_connection_id is not None:
                peer = online.get(preferred_connection_id)
                if peer is None:
                    raise GatewayCallError(
                        "ABM_EXTENSION_OFFLINE",
                        "The selected browser connection is offline.",
                        retryable=True,
                        action="open_extension",
                    )
                candidates = [preferred_connection_id]
            elif preferred_api_key_id is not None:
                candidates = [
                    connection_id
                    for connection_id, peer in online.items()
                    if peer.api_key_id == preferred_api_key_id
                ]
                if not candidates:
                    raise GatewayCallError(
                        "ABM_EXTENSION_OFFLINE",
                        "No online extension is available for the current API Key.",
                        retryable=True,
                        action="wait",
                    )
            else:
                candidates = list(online)

            max_sessions = max(1, session_limit)
            reserved = max(0, reserved_limit)
            normal_cap = max(1, max_sessions - reserved)
            free = []
            for connection_id in candidates:
                peer = self._connections[connection_id]
                if not peer.capabilities.get("sharedSessions"):
                    cap = 1
                elif priority > 0:
                    cap = max_sessions
                else:
                    cap = normal_cap
                if self._session_count(connection_id) < cap:
                    free.append(connection_id)
            if not free:
                if online:
                    raise GatewayCallError(
                        "ABM_CONNECTION_BUSY",
                        "All browser connections for the current account are in use "
                        "by other sessions. Try again later.",
                        retryable=True,
                        action="wait",
                    )
                raise GatewayCallError(
                    "ABM_EXTENSION_OFFLINE",
                    "No online browser extension is available for the current "
                    "account. Configure an API Key in the extension and connect it first.",
                    retryable=True,
                    action="open_extension",
                )

            free.sort(key=lambda connection_id: (self._session_count(connection_id), connection_id))
            cursor = self._lease_cursor.get(user_id, 0)
            chosen = free[cursor % len(free)]
            self._lease_cursor[user_id] = cursor + 1
            self._leases[key] = ConnectionLease(
                user_id=user_id,
                session_id=session_id,
                api_key_id=self._connections[chosen].api_key_id,
                connection_id=chosen,
                created_at=now,
                last_used_at=now,
                expires_at=now + timedelta(seconds=ttl),
                group_title=group_title,
                collapsed=collapsed,
                priority=priority,
            )
            self._lease_owners.setdefault(chosen, key)
            return chosen

    async def update_extension_id(self, peer: GatewayPeer, extension_id: str) -> None:
        async with self._state_lock:
            peer.extension_id = extension_id

    @staticmethod
    def peer_info(peer: GatewayPeer) -> dict[str, Any]:
        return {
            "connectionId": peer.connection_id,
            "browserId": peer.browser_id,
            "apiKeyId": peer.api_key_id,
            "extensionId": peer.extension_id,
            "extensionVersion": peer.extension_version,
            "capabilities": dict(peer.capabilities),
            "connectedAt": peer.connected_at.isoformat(),
            "lastSeen": peer.last_seen.isoformat(),
        }

    def connection_info(self, identifier: str) -> dict[str, Any] | None:
        peer = self.get_peer(identifier)
        return self.peer_info(peer) if peer is not None else None

    def connections_info(self, api_key_id: str) -> list[dict[str, Any]]:
        return [
            self.peer_info(peer)
            for peer in self._connections.values()
            if peer.api_key_id == api_key_id and peer.active
        ]

    def pending_count(self, api_key_id: str | None = None) -> int:
        if api_key_id is None:
            return len(self._pending)
        return sum(1 for item in self._pending.values() if item.api_key_id == api_key_id)

    async def send_error_and_close(self, peer: GatewayPeer, error: SessionError) -> None:
        await peer.send(error_envelope(error))
        peer.active = False
        try:
            await peer.websocket.close(code=error.close_code, reason=error.code)
        except Exception:
            logger.debug("WebSocket already closed", exc_info=True)

    async def close_peer(self, peer: GatewayPeer, error: SessionError) -> None:
        await self.reject_pending_for_connection(
            peer.connection_id,
            GatewayCallError(error.code, error.message, action=error.action),
        )
        await self.send_error_and_close(peer, error)

    async def close_for_key(self, api_key_id: str, error: SessionError) -> bool:
        peers = [peer for peer in self._connections.values() if peer.api_key_id == api_key_id]
        for peer in peers:
            await self.close_peer(peer, error)
        return bool(peers)

    async def close_for_user(self, user_id: str, error: SessionError) -> int:
        peers = [peer for peer in self._connections.values() if peer.user_id == user_id]
        for peer in peers:
            await self.close_peer(peer, error)
        return len(peers)

    async def reject_pending_for_key(
        self,
        api_key_id: str,
        error: GatewayCallError,
    ) -> None:
        async with self._state_lock:
            pending = [
                (request_id, item)
                for request_id, item in self._pending.items()
                if item.api_key_id == api_key_id
            ]
            for request_id, _ in pending:
                self._pending.pop(request_id, None)
        for _, item in pending:
            if not item.future.done():
                item.future.set_exception(error)

    async def reject_pending_for_connection(
        self,
        connection_id: str,
        error: GatewayCallError,
    ) -> None:
        async with self._state_lock:
            pending = [
                (request_id, item)
                for request_id, item in self._pending.items()
                if item.connection_id == connection_id
            ]
            for request_id, _ in pending:
                self._pending.pop(request_id, None)
        for _, item in pending:
            if not item.future.done():
                item.future.set_exception(error)

    async def call_tool(
        self,
        *,
        connection_id: str | None = None,
        api_key_id: str | None = None,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        peer = self.get_peer(connection_id or api_key_id or "")
        if peer is None and api_key_id is not None:
            peer = self.get_peer(api_key_id)
        if peer is None or not peer.active:
            raise GatewayCallError(
                "ABM_EXTENSION_OFFLINE",
                "No online extension is available for the current API Key.",
                retryable=True,
                action="wait",
            )
        request_id = f"call_{uuid4().hex}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        pending = PendingCall(
            api_key_id=peer.api_key_id,
            connection_id=peer.connection_id,
            tool_name=name,
            future=future,
            started_at=datetime.now(UTC),
        )
        async with self._state_lock:
            self._pending[request_id] = pending
        sent = await peer.send(
            envelope(
                "tool.invoke",
                {"name": name, "arguments": arguments, "context": context or {}},
                message_id=request_id,
            )
        )
        if not sent:
            async with self._state_lock:
                self._pending.pop(request_id, None)
            raise GatewayCallError(
                "ABM_EXTENSION_OFFLINE",
                "Extension connection closed.",
                retryable=True,
                action="wait",
            )
        timeout = (timeout_ms or self.settings.tool_timeout_ms) / 1000
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise GatewayCallError(
                "ABM_TOOL_TIMEOUT",
                f"Tool {name} did not return a result within {int(timeout * 1000)}ms.",
                retryable=True,
                action="wait",
            ) from exc
        finally:
            async with self._state_lock:
                self._pending.pop(request_id, None)

    async def accept_tool_result(
        self,
        *,
        api_key_id: str | None = None,
        connection_id: str | None = None,
        message_id: str | None,
        payload: dict[str, Any],
    ) -> bool:
        if not message_id:
            return False
        async with self._state_lock:
            pending = self._pending.get(message_id)
            if pending is None:
                return False
            if connection_id is not None and pending.connection_id != connection_id:
                return False
            if (
                connection_id is None
                and api_key_id is not None
                and pending.api_key_id != api_key_id
            ):
                return False
            self._pending.pop(message_id, None)
        if pending.future.done():
            return False
        if payload.get("status") == "ok":
            pending.future.set_result(payload)
        else:
            error = payload.get("error")
            if isinstance(error, dict):
                pending.future.set_exception(
                    GatewayCallError(
                        str(error.get("code") or "ABM_TOOL_EXECUTION_FAILED"),
                        str(error.get("message") or "Tool execution failed."),
                    )
                )
            else:
                pending.future.set_exception(
                    GatewayCallError("ABM_TOOL_EXECUTION_FAILED", "Tool execution failed.")
                )
        return True

    async def send_notice(
        self,
        *,
        api_key_id: str,
        notice_id: str,
        title: str,
        level: str,
        body: str | None,
        action_url: str | None,
    ) -> bool:
        peers = [
            peer
            for peer in self._connections.values()
            if peer.api_key_id == api_key_id and peer.active
        ]
        if not peers:
            return False
        sent = False
        for peer in peers:
            sent = (
                await peer.send(
                    envelope(
                        "notice.push",
                        {
                            "id": notice_id,
                            "title": title,
                            "level": level,
                            "body": body,
                            "actionUrl": action_url,
                        },
                    )
                )
                or sent
            )
        return sent

    async def heartbeat_loop(self, peer: GatewayPeer) -> None:
        heartbeat_seconds = self.settings.heartbeat_ms / 1000
        stale_seconds = self.settings.stale_timeout_ms / 1000
        try:
            while peer.active:
                await asyncio.sleep(heartbeat_seconds)
                now = datetime.now(UTC)
                if (now - peer.last_seen).total_seconds() > stale_seconds:
                    await self.send_error_and_close(
                        peer,
                        SessionError(
                            "ABM_HEARTBEAT_TIMEOUT",
                            "Extension heartbeat timed out.",
                            1001,
                            retryable=True,
                            action="wait",
                        ),
                    )
                    return
                if not await peer.send(envelope("session.ping")):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat loop failed")

    async def shutdown(self) -> None:
        peers = list(self._connections.values())
        for peer in peers:
            await self.send_error_and_close(
                peer,
                SessionError(
                    "ABM_SERVER_SHUTTING_DOWN",
                    "Server is shutting down.",
                    1001,
                    retryable=True,
                    action="wait",
                ),
            )
        self._connections.clear()
        self._key_connections.clear()
        self._leases.clear()
        self._lease_owners.clear()
        self._lease_cursor.clear()
