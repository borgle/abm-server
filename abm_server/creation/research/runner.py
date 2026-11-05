"""In-process research job runner.

The runner calls the extension gateway directly (web-initiated jobs) or a fake
driver in tests. It stores every meaningful step as an append-only event so the
SSE endpoint can replay from ``Last-Event-ID``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select

from ...config import Settings
from ...database import Database
from ...extension_gateway import GatewayCallError
from ...models import (
    CreationJobEvent,
    CreationResearchJob,
    CreationSource,
    utcnow,
)
from . import adapters
from .planner import normalize_engines, pages_for_depth

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled"}


class BrowserDriver(Protocol):
    async def navigate(self, url: str, *, reuse_key: str) -> Any: ...

    async def extract(self, script: str, args: dict[str, Any]) -> Any: ...


class GatewayDriver:
    def __init__(
        self,
        gateway: Any,
        connection_id: str,
        *,
        task_id: str,
        group_title: str,
    ) -> None:
        self._gateway = gateway
        self._connection_id = connection_id
        self._context = {
            "taskId": task_id,
            "groupTitle": group_title,
            "collapsed": True,
        }
        self._tab_id: int | None = None

    def _call(self, name: str, arguments: dict[str, Any], timeout_ms: int | None = None) -> Any:
        return self._gateway.call_tool(
            connection_id=self._connection_id,
            name=name,
            arguments=arguments,
            context=self._context,
            timeout_ms=timeout_ms,
        )

    def fork(self) -> GatewayDriver:
        """Return a driver sharing the same browser session but its own tab."""

        return GatewayDriver(
            self._gateway,
            self._connection_id,
            task_id=str(self._context.get("taskId") or ""),
            group_title=str(self._context.get("groupTitle") or ""),
        )

    async def navigate(self, url: str, *, reuse_key: str) -> Any:
        result = await self._call(
            "browser_navigate",
            {
                "url": url,
                "waitUntil": "load",
                "timeout": 45_000,
                "reuseKey": reuse_key,
                "background": True,
            },
        )
        payload = adapters.parse_tool_result(result)
        if isinstance(payload, dict):
            tab_id = payload.get("tabId")
            if isinstance(tab_id, int):
                self._tab_id = tab_id
        return result

    async def extract(self, script: str, args: dict[str, Any]) -> Any:
        arguments: dict[str, Any] = {"code": script, "args": args}
        if self._tab_id is not None:
            arguments["tabId"] = self._tab_id
        return await self._call("browser_inject_script", arguments)

    async def wait(self, selector: str, timeout_ms: int = 6000) -> Any:
        arguments: dict[str, Any] = {
            "selector": selector,
            "count": 1,
            "timeout": timeout_ms,
        }
        if self._tab_id is not None:
            arguments["tabId"] = self._tab_id
        return await self._call(
            "browser_wait_elements",
            arguments,
            timeout_ms + 5000,
        )


class ResearchRunner:
    def __init__(
        self,
        database: Database,
        gateway: Any,
        settings: Settings,
    ) -> None:
        self.database = database
        self.gateway = gateway
        self.settings = settings
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()
        self._paused: set[str] = set()
        self._attention_tasks: dict[str, asyncio.Task[None]] = {}
        self._maintenance: asyncio.Task[None] | None = None

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._maintenance is None:
            self._maintenance = asyncio.create_task(self._maintenance_loop())

    async def shutdown(self) -> None:
        if self._maintenance is not None:
            self._maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance
            self._maintenance = None
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        for task in list(self._attention_tasks.values()):
            task.cancel()
        self._attention_tasks.clear()

    async def mark_interrupted(self) -> int:
        """Flag jobs left running by a previous process."""
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(CreationResearchJob).where(
                        CreationResearchJob.status.in_(["queued", "running"])
                    )
                )
            ).all()
            now = utcnow()
            for job in rows:
                job.status = "interrupted"
                job.updated_at = now
            await session.commit()
            return len(rows)

    def is_running(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        return task is not None and not task.done()

    def launch(self, job_id: str) -> None:
        if self.is_running(job_id):
            return
        task = asyncio.create_task(self._guarded_run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    def cancel(self, job_id: str) -> None:
        self._cancel_attention_task(job_id)
        self._cancelled.add(job_id)

    async def pause(self, job_id: str) -> None:
        self._paused.add(job_id)
        job = await self._load_job(job_id)
        if job is not None and job.status in {"queued", "running"}:
            await self._set_status(job_id, "paused")

    async def resume(
        self,
        job_id: str,
        skip_engine: str | None = None,
        skip_current: bool = False,
    ) -> None:
        self._cancel_attention_task(job_id)
        self._paused.discard(job_id)
        self._cancelled.discard(job_id)
        if skip_engine or skip_current:
            async with self.database.sessions() as session:
                job = await session.get(CreationResearchJob, job_id)
                if job is not None:
                    progress = dict(job.progress or {})
                    attention = dict(job.attention or {})
                    if skip_engine:
                        skipped = set(progress.get("skippedEngines") or [])
                        skipped.add(skip_engine)
                        progress["skippedEngines"] = sorted(skipped)
                    if skip_current:
                        phase = str(attention.get("phase") or "fetch")
                        if phase == "search":
                            engine_id = str(attention.get("engine") or "")
                            if engine_id:
                                skipped = set(progress.get("skippedEngines") or [])
                                skipped.add(engine_id)
                                progress["skippedEngines"] = sorted(skipped)
                        else:
                            url = str(attention.get("url") or "")
                            if url:
                                visited = set(progress.get("visited") or [])
                                visited.add(url)
                                progress["visited"] = sorted(visited)[-200:]
                    job.progress = progress
                    job.updated_at = utcnow()
                    await session.commit()
        await self._set_status(job_id, "queued", clear_attention=True)
        self.launch(job_id)

    async def _guarded_run(self, job_id: str) -> None:
        try:
            await self.run_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - background job must not crash the app
            logger.exception("Creation research job %s crashed", job_id)
            await self._set_status(
                job_id,
                "failed",
                error_code="ABM_INTERNAL_ERROR",
                error_message="The research job stopped unexpectedly.",
            )

    # -- job execution -----------------------------------------------------
    async def run_job(self, job_id: str, driver: BrowserDriver | None = None) -> None:
        job = await self._load_job(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return
        if job.status == "paused" and job_id not in self._cancelled:
            # A paused job only moves when an explicit resume launches it.
            return

        seq = await self._next_seq(job_id)
        plan = list(job.plan or [])
        budget = pages_for_depth(job.depth)
        progress = dict(job.progress or {})
        visited: set[str] = set(progress.get("visited") or [])
        skipped_engines: set[str] = set(progress.get("skippedEngines") or [])
        query_index = int(progress.get("queryIndex") or 0)
        engine_index = int(progress.get("engineIndex") or 0)
        user_id = job.user_id
        session_id = f"creation:{job.id}"
        leased = driver is None
        errors: list[dict[str, Any]] = []
        searches_completed = 0

        if driver is None:
            keywords = [str(item) for item in (job.keywords or []) if str(item).strip()]
            group_title = "ABM · 检索"
            if keywords:
                group_title = f"ABM · 检索 · {keywords[0][:24]}"
            driver = await self._acquire_driver(
                user_id,
                session_id,
                job_id,
                seq,
                group_title=group_title,
            )
            if driver is None:
                return
            # _acquire_driver emits connection.acquired with the current seq.
            seq += 1

        await self._update_job(
            job_id,
            status="running",
            started_at=job.started_at or utcnow(),
            attention=None,
            error_code=None,
            error_message=None,
        )
        await self._emit(job_id, user_id, seq, "job.started", "Research job started.")
        seq += 1

        collected = job.pages_collected
        failed = job.pages_failed
        completed_queries = job.completed_queries

        try:
            while query_index < len(plan):
                if job_id in self._paused:
                    await self._pause_exit(job_id, user_id, seq)
                    return
                if job_id in self._cancelled:
                    await self._finish_cancelled(job_id, seq)
                    return
                query = plan[query_index]
                query_text = str(query.get("query") or "")
                engines = normalize_engines(query.get("engines") or job.engines)
                prefetched: dict[str, Any] = {}
                fork = getattr(driver, "fork", None)
                parallel = max(1, int(getattr(self.settings, "research_parallel_searches", 1)))
                if fork is not None and parallel > 1 and collected < budget:
                    pending = [
                        engine_id
                        for engine_id in engines[engine_index:]
                        if engine_id not in skipped_engines
                        and adapters.SEARCH_ENGINES.get(engine_id) is not None
                    ]
                    if len(pending) > 1:
                        for engine_id in pending:
                            engine = adapters.SEARCH_ENGINES[engine_id]
                            await self._emit(
                                job_id,
                                user_id,
                                seq,
                                "search.started",
                                f"Searching {engine['label']}: {query_text}",
                                {
                                    "engine": engine_id,
                                    "query": query_text,
                                    "parallel": True,
                                },
                            )
                            seq += 1
                        prefetched = await self._prefetch_searches(
                            driver,
                            pending,
                            query_text,
                            job_id,
                            parallel,
                        )
                while engine_index < len(engines):
                    engine_id = engines[engine_index]
                    engine = adapters.SEARCH_ENGINES.get(engine_id)
                    if engine is None or engine_id in skipped_engines:
                        engine_index += 1
                        continue
                    if collected >= budget:
                        break
                    try:
                        if engine_id in prefetched:
                            value = prefetched[engine_id]
                            if isinstance(value, GatewayCallError):
                                raise value
                            payload = value
                        else:
                            await self._emit(
                                job_id,
                                user_id,
                                seq,
                                "search.started",
                                f"Searching {engine['label']}: {query_text}",
                                {"engine": engine_id, "query": query_text},
                            )
                            seq += 1
                            payload = await self._search(
                                driver,
                                engine_id,
                                engine,
                                query_text,
                                job_id,
                            )
                    except GatewayCallError as exc:
                        if self._should_wait(exc):
                            await self._needs_attention(
                                job_id,
                                user_id,
                                seq,
                                self._attention_payload(exc),
                            )
                            return
                        failed += 1
                        await self._note_error(
                            job_id,
                            user_id,
                            seq,
                            step="search",
                            code=exc.code,
                            message=f"{engine['label']} search failed: {exc.message}",
                            context={"engine": engine_id, "query": query_text},
                            errors=errors,
                        )
                        seq += 1
                        engine_index += 1
                        continue

                    parsed = adapters.parse_tool_result(payload)
                    if not isinstance(parsed, dict):
                        failed += 1
                        await self._note_error(
                            job_id,
                            user_id,
                            seq,
                            step="search",
                            code="ABM_RESEARCH_BAD_PAYLOAD",
                            message="The browser returned an unexpected search payload.",
                            context={
                                "engine": engine_id,
                                "payload": _payload_preview(payload),
                            },
                            errors=errors,
                        )
                        seq += 1
                        engine_index += 1
                        continue
                    tool_error = _tool_error(parsed)
                    if tool_error is not None:
                        failed += 1
                        await self._note_error(
                            job_id,
                            user_id,
                            seq,
                            step="search",
                            code=tool_error["code"],
                            message=f"{engine['label']} search failed: {tool_error['message']}",
                            context={"engine": engine_id, "query": query_text},
                            errors=errors,
                        )
                        seq += 1
                        engine_index += 1
                        continue

                    results, attention = adapters.search_results(payload)
                    searches_completed += 1
                    await self._emit(
                        job_id,
                        user_id,
                        seq,
                        "search.completed",
                        f"{engine['label']} returned {len(results)} results.",
                        {"engine": engine_id, "count": len(results)},
                    )
                    seq += 1
                    if attention:
                        if self.settings.research_pause_on_interstitial and self._should_pause(
                            attention
                        ):
                            await self._needs_attention(
                                job_id,
                                user_id,
                                seq,
                                {
                                    **attention,
                                    "engine": engine_id,
                                    "query": query_text,
                                    "phase": "search",
                                    "url": adapters.search_url(engine_id, query_text),
                                },
                            )
                            self._schedule_attention_skip(job_id, skip_engine=engine_id)
                            return
                        skipped_engines.add(engine_id)
                        failed += 1
                        await self._skip_engine(
                            job_id,
                            user_id,
                            seq,
                            engine_id=engine_id,
                            label=str(engine["label"]),
                            attention=attention,
                            skipped=skipped_engines,
                            errors=errors,
                        )
                        seq += 1
                        engine_index += 1
                        continue
                    if not results:
                        await self._emit(
                            job_id,
                            user_id,
                            seq,
                            "search.empty",
                            f"{engine['label']} returned no parsable results. "
                            "The page layout may have changed or the page did not load.",
                            {
                                "engine": engine_id,
                                "query": query_text,
                                "title": str(parsed.get("title") or "")[:200],
                            },
                            level="warn",
                        )
                        seq += 1
                        await self._set_progress_stage(job_id, "search", query_text, engine_id)
                        engine_index += 1
                        continue

                    await self._set_progress_stage(job_id, "fetch", query_text, engine_id)
                    for item in results:
                        if collected >= budget:
                            break
                        if job_id in self._paused:
                            await self._pause_exit(job_id, user_id, seq)
                            return
                        if job_id in self._cancelled:
                            await self._finish_cancelled(job_id, seq)
                            return
                        canonical = item["url"]
                        if canonical in visited:
                            continue
                        visited.add(canonical)
                        script = (
                            adapters.XHS_NOTE_SCRIPT
                            if engine_id == "xiaohongshu"
                            else adapters.ARTICLE_SCRIPT
                        )
                        try:
                            nav = await driver.navigate(canonical, reuse_key=f"creation-{job.id}")
                            nav_error = _payload_error(nav)
                            if nav_error is not None:
                                raise GatewayCallError(nav_error["code"], nav_error["message"])
                            article = await driver.extract(
                                script,
                                {"maxLength": 8000 if engine_id == "xiaohongshu" else 20000},
                            )
                        except GatewayCallError as exc:
                            if self._should_wait(exc):
                                await self._needs_attention(
                                    job_id,
                                    user_id,
                                    seq,
                                    self._attention_payload(exc),
                                )
                                return
                            failed += 1
                            await self._note_error(
                                job_id,
                                user_id,
                                seq,
                                step="fetch",
                                code=exc.code,
                                message=f"Could not read {canonical}: {exc.message}",
                                context={"url": canonical},
                                errors=errors,
                            )
                            seq += 1
                            continue

                        parsed_article = adapters.parse_tool_result(article)
                        if not isinstance(parsed_article, dict):
                            failed += 1
                            await self._note_error(
                                job_id,
                                user_id,
                                seq,
                                step="fetch",
                                code="ABM_RESEARCH_BAD_PAYLOAD",
                                message=(
                                    f"The browser returned an unexpected payload for {canonical}."
                                ),
                                context={
                                    "url": canonical,
                                    "payload": _payload_preview(article),
                                },
                                errors=errors,
                            )
                            seq += 1
                            continue
                        tool_error = _tool_error(parsed_article)
                        if tool_error is not None:
                            failed += 1
                            await self._note_error(
                                job_id,
                                user_id,
                                seq,
                                step="fetch",
                                code=tool_error["code"],
                                message=f"Could not read {canonical}: {tool_error['message']}",
                                context={"url": canonical},
                                errors=errors,
                            )
                            seq += 1
                            continue

                        data, attention = adapters.article_payload(article)
                        if attention:
                            if self.settings.research_pause_on_interstitial and self._should_pause(
                                attention
                            ):
                                visited.discard(canonical)
                                await self._update_progress(
                                    job_id,
                                    {"visited": sorted(visited)[-200:]},
                                )
                                await self._needs_attention(
                                    job_id,
                                    user_id,
                                    seq,
                                    {
                                        **attention,
                                        "engine": engine_id,
                                        "url": canonical,
                                        "query": query_text,
                                        "phase": "fetch",
                                    },
                                )
                                self._schedule_attention_skip(job_id, skip_current=True)
                                return
                            failed += 1
                            await self._note_error(
                                job_id,
                                user_id,
                                seq,
                                step="fetch",
                                code=_attention_code(attention),
                                message=(
                                    f"Skipped {canonical}: "
                                    f"{attention.get('message') or 'site requires attention'}"
                                ),
                                context={
                                    "url": canonical,
                                    "reason": attention.get("reason"),
                                },
                                errors=errors,
                            )
                            seq += 1
                            continue
                        if data is None:
                            failed += 1
                            await self._note_error(
                                job_id,
                                user_id,
                                seq,
                                step="fetch",
                                code="ABM_RESEARCH_EMPTY_PAGE",
                                message=f"No readable text on {canonical}.",
                                context={
                                    "url": canonical,
                                    "title": str(parsed_article.get("title") or "")[:200],
                                },
                                errors=errors,
                            )
                            seq += 1
                            continue

                        save = await self._save_source(
                            user_id=user_id,
                            job=job,
                            engine_id=engine_id,
                            item=item,
                            data=data,
                        )
                        if save is None:
                            await self._emit(
                                job_id,
                                user_id,
                                seq,
                                "source.duplicate",
                                f"Skipped duplicate {canonical}.",
                                {"url": canonical},
                            )
                            seq += 1
                            continue
                        collected += 1
                        await self._emit(
                            job_id,
                            user_id,
                            seq,
                            "source.saved",
                            f"Saved {save['title'] or save['domain']}.",
                            {
                                "sourceId": save["id"],
                                "title": save["title"],
                                "domain": save["domain"],
                                "credibility": save["credibility"],
                            },
                        )
                        seq += 1
                        await self._update_progress(
                            job_id,
                            {
                                "queryIndex": query_index,
                                "engineIndex": engine_index,
                                "visited": sorted(visited)[-200:],
                                "collected": collected,
                            },
                            pages_collected=collected,
                            pages_failed=failed,
                        )

                    engine_index += 1
                    await self._update_progress(
                        job_id,
                        {
                            "queryIndex": query_index,
                            "engineIndex": engine_index,
                            "visited": sorted(visited)[-200:],
                            "collected": collected,
                        },
                        completed_queries=completed_queries,
                    )
                query_index += 1
                engine_index = 0
                completed_queries = min(len(plan), query_index)
                await self._update_progress(
                    job_id,
                    {
                        "queryIndex": query_index,
                        "engineIndex": 0,
                        "visited": sorted(visited)[-200:],
                        "collected": collected,
                    },
                    completed_queries=completed_queries,
                    pages_collected=collected,
                    pages_failed=failed,
                )
                if collected >= budget:
                    break

            status, error_code, error_message = self._final_status(
                collected=collected,
                failed=failed,
                searches_completed=searches_completed,
                errors=errors,
            )
            await self._set_status(
                job_id,
                status,
                finished=True,
                pages_collected=collected,
                pages_failed=failed,
                completed_queries=completed_queries,
                error_code=error_code,
                error_message=error_message,
            )
            await self._emit(
                job_id,
                user_id,
                seq,
                "job.finished",
                error_message or f"Research finished with {collected} sources.",
                {
                    "status": status,
                    "collected": collected,
                    "failed": failed,
                    "errorCode": error_code,
                },
                level="warn" if status in {"partial", "failed"} else "info",
            )
        except Exception as exc:  # noqa: BLE001 - persist the reason before failing
            logger.exception("Research job %s failed", job_id)
            message = f"{type(exc).__name__}: {exc}"
            await self._set_status(
                job_id,
                "failed",
                finished=True,
                error_code="ABM_INTERNAL_ERROR",
                error_message=message[:500],
            )
            with contextlib.suppress(Exception):
                await self._emit(
                    job_id,
                    user_id,
                    seq,
                    "job.failed",
                    f"Research job stopped unexpectedly: {message[:300]}",
                    {"status": "failed", "errorCode": "ABM_INTERNAL_ERROR"},
                    level="error",
                )
        finally:
            if leased:
                await self.gateway.release_session(user_id, session_id)

    def _cancel_attention_task(self, job_id: str) -> None:
        task = self._attention_tasks.pop(job_id, None)
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _schedule_attention_skip(
        self,
        job_id: str,
        *,
        skip_engine: str | None = None,
        skip_current: bool = False,
    ) -> None:
        timeout = int(self.settings.research_attention_timeout_seconds)
        if timeout <= 0:
            return
        self._cancel_attention_task(job_id)

        async def run() -> None:
            await asyncio.sleep(timeout)
            job = await self._load_job(job_id)
            if job is None or job.status != "needs_attention":
                return
            await self.resume(job_id, skip_engine=skip_engine, skip_current=skip_current)

        self._attention_tasks[job_id] = asyncio.create_task(run())

    @staticmethod
    def _should_pause(attention: dict[str, Any]) -> bool:
        reason = attention.get("reason")
        return reason in {"captcha", "blocked", "login_required"}

    @staticmethod
    def _should_wait(exc: GatewayCallError) -> bool:
        return exc.code in {"ABM_EXTENSION_OFFLINE", "ABM_CONNECTION_BUSY"}

    @staticmethod
    def _attention_payload(exc: GatewayCallError) -> dict[str, Any]:
        reason = "connection_busy" if exc.code == "ABM_CONNECTION_BUSY" else "extension_offline"
        return {"reason": reason, "message": exc.message, "action": exc.action}

    async def _skip_engine(
        self,
        job_id: str,
        user_id: str,
        seq: int,
        *,
        engine_id: str,
        label: str,
        attention: dict[str, Any],
        skipped: set[str],
        errors: list[dict[str, Any]],
    ) -> None:
        await self._note_error(
            job_id,
            user_id,
            seq,
            step="search",
            code=_attention_code(attention),
            message=(f"{label} skipped: {attention.get('message') or 'site requires attention'}"),
            context={"engine": engine_id, "reason": attention.get("reason")},
            errors=errors,
        )
        await self._update_progress(job_id, {"skippedEngines": sorted(skipped)})

    @staticmethod
    def _final_status(
        *,
        collected: int,
        failed: int,
        searches_completed: int,
        errors: list[dict[str, Any]],
    ) -> tuple[str, str | None, str | None]:
        first = errors[0] if errors else None
        if collected == 0:
            if first is not None:
                return (
                    "partial" if searches_completed else "failed",
                    first["code"],
                    first["message"],
                )
            return (
                "partial",
                "ABM_RESEARCH_NO_RESULTS",
                "Searches completed but returned no parsable results. "
                "Check the search page in your browser.",
            )
        if failed or errors:
            detail = first["message"] if first else f"{failed} pages failed."
            return "partial", "ABM_RESEARCH_PARTIAL", f"Partly completed: {detail}"
        return "completed", None, None

    async def _note_error(
        self,
        job_id: str,
        user_id: str,
        seq: int,
        *,
        step: str,
        code: str,
        message: str,
        context: dict[str, Any] | None = None,
        errors: list[dict[str, Any]],
    ) -> None:
        entry = {
            "step": step,
            "code": code,
            "message": message,
            "context": context or {},
            "at": utcnow().isoformat(),
        }
        errors.append(entry)
        if len(errors) > 10:
            errors.pop(0)
        logger.warning("Research job %s failed at %s: %s (%s)", job_id, step, message, code)
        await self._emit(
            job_id,
            user_id,
            seq,
            f"{step}.failed",
            message,
            {"step": step, "code": code, **(context or {})},
            level="warn",
        )
        await self._store_last_error(job_id, entry)

    async def _store_last_error(self, job_id: str, entry: dict[str, Any]) -> None:
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            progress = dict(job.progress or {})
            progress["lastError"] = entry
            job.progress = progress
            job.updated_at = utcnow()
            await session.commit()

    async def _set_progress_stage(self, job_id: str, stage: str, query: str, engine: str) -> None:
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            progress = dict(job.progress or {})
            progress["stage"] = stage
            progress["currentQuery"] = query
            progress["currentEngine"] = engine
            job.progress = progress
            job.updated_at = utcnow()
            await session.commit()

    # -- helpers -----------------------------------------------------------
    async def _load_job(self, job_id: str) -> CreationResearchJob | None:
        async with self.database.sessions() as session:
            return await session.get(CreationResearchJob, job_id)

    async def _search(
        self,
        driver: BrowserDriver,
        engine_id: str,
        engine: dict[str, Any],
        query_text: str,
        job_id: str,
    ) -> Any:
        """Run one engine search and return the raw tool payload."""

        nav = await driver.navigate(
            adapters.search_url(engine_id, query_text),
            reuse_key=f"creation-{job_id}-search-{engine_id}",
        )
        nav_error = _payload_error(nav)
        if nav_error is not None:
            raise GatewayCallError(nav_error["code"], nav_error["message"])
        wait = getattr(driver, "wait", None)
        if wait is not None:
            for selector in engine["selectors"][:2]:
                try:
                    await wait(selector, 6000)
                    break
                except GatewayCallError:
                    continue
        return await driver.extract(
            adapters.SEARCH_SCRIPT,
            {"selectors": engine["selectors"], "limit": 10},
        )

    async def _prefetch_searches(
        self,
        driver: BrowserDriver,
        engine_ids: list[str],
        query_text: str,
        job_id: str,
        parallel: int,
    ) -> dict[str, Any]:
        """Search several engines at once, each in its own tab."""

        semaphore = asyncio.Semaphore(max(1, parallel))

        async def run(engine_id: str) -> tuple[str, Any]:
            engine = adapters.SEARCH_ENGINES[engine_id]
            async with semaphore:
                try:
                    payload = await self._search(
                        driver.fork(),  # type: ignore[attr-defined]
                        engine_id,
                        engine,
                        query_text,
                        job_id,
                    )
                except GatewayCallError as exc:
                    return engine_id, exc
                except Exception as exc:  # noqa: BLE001 - surfaced per engine
                    logger.exception("Parallel search failed for %s", engine_id)
                    return engine_id, GatewayCallError(
                        "ABM_RESEARCH_SEARCH_FAILED",
                        str(exc),
                        retryable=True,
                        action="retry",
                    )
                return engine_id, payload

        results = await asyncio.gather(*(run(engine_id) for engine_id in engine_ids))
        return dict(results)

    async def _acquire_driver(
        self,
        user_id: str,
        session_id: str,
        job_id: str,
        seq: int,
        *,
        group_title: str,
    ) -> BrowserDriver | None:
        try:
            connection_id = await self.gateway.acquire_connection_for_session(
                user_id=user_id,
                session_id=session_id,
                ttl_seconds=1800,
                group_title=group_title,
                collapsed=True,
            )
        except GatewayCallError as exc:
            await self._needs_attention(
                job_id,
                user_id,
                seq,
                self._attention_payload(exc),
            )
            return None
        await self._emit(
            job_id,
            user_id,
            seq,
            "connection.acquired",
            "Connected to the browser extension.",
            {"connectionId": connection_id},
        )
        return GatewayDriver(
            self.gateway,
            connection_id,
            task_id=session_id,
            group_title=group_title,
        )

    async def _next_seq(self, job_id: str) -> int:
        async with self.database.sessions() as session:
            value = await session.scalar(
                select(func.max(CreationJobEvent.seq)).where(CreationJobEvent.job_id == job_id)
            )
            return int(value or 0) + 1

    async def _emit(
        self,
        job_id: str,
        user_id: str,
        seq: int,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
        *,
        level: str = "info",
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                CreationJobEvent(
                    job_id=job_id,
                    user_id=user_id,
                    seq=seq,
                    level=level,
                    message=message,
                    data={"type": event_type, **(data or {})},
                )
            )
            job = await session.get(CreationResearchJob, job_id)
            if job is not None:
                job.updated_at = utcnow()
            await session.commit()

    async def _update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        started_at: Any = None,
        attention: Any = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            if status:
                job.status = status
            if started_at is not None:
                job.started_at = started_at
            if attention is not None or status in {"running", "completed", "partial"}:
                job.attention = attention
            if error_code is not None or status == "running":
                job.error_code = error_code
            if error_message is not None or status == "running":
                job.error_message = error_message
            job.updated_at = utcnow()
            await session.commit()

    async def _update_progress(
        self,
        job_id: str,
        progress: dict[str, Any],
        **counters: int,
    ) -> None:
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            merged = dict(job.progress or {})
            merged.update(progress)
            job.progress = merged
            for key, value in counters.items():
                setattr(job, key, value)
            job.updated_at = utcnow()
            await session.commit()

    async def _set_status(
        self,
        job_id: str,
        status: str,
        *,
        finished: bool = False,
        clear_attention: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
        **counters: int,
    ) -> None:
        if job_id in self._cancelled and status != "cancelled":
            status = "cancelled"
            finished = True
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            job.status = status
            job.updated_at = utcnow()
            if finished:
                job.finished_at = utcnow()
            if clear_attention:
                job.attention = None
            if error_code:
                job.error_code = error_code
                job.error_message = error_message
            for key, value in counters.items():
                setattr(job, key, value)
            await session.commit()

    async def _pause_exit(self, job_id: str, user_id: str, seq: int) -> None:
        await self._set_status(job_id, "paused")
        await self._emit(
            job_id,
            user_id,
            seq,
            "job.paused",
            "Research job paused.",
            {"status": "paused"},
        )

    async def _needs_attention(
        self,
        job_id: str,
        user_id: str,
        seq: int,
        attention: dict[str, Any],
    ) -> None:
        if job_id in self._cancelled:
            await self._finish_cancelled(job_id, seq)
            return
        async with self.database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            if job is None:
                return
            job.status = "needs_attention"
            job.attention = attention
            job.updated_at = utcnow()
            await session.commit()
        await self._emit(
            job_id,
            user_id,
            seq,
            "attention.required",
            attention.get("message") or "The research job needs your attention.",
            attention,
            level="warn",
        )

    async def _finish_cancelled(self, job_id: str, seq: int) -> None:
        job = await self._load_job(job_id)
        if job is None:
            return
        await self._set_status(job_id, "cancelled", finished=True)
        await self._emit(
            job_id,
            job.user_id,
            seq,
            "job.cancelled",
            "Research job cancelled.",
            {"status": "cancelled"},
        )

    async def _save_source(
        self,
        *,
        user_id: str,
        job: CreationResearchJob,
        engine_id: str,
        item: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        url = item["url"]
        canonical = data.get("canonical") or url
        text = data.get("text") or ""
        fingerprint = adapters.fingerprint_text(text)
        score, factors = adapters.score_credibility(
            url=canonical,
            author=data.get("author"),
            published=data.get("published"),
            text=text,
        )
        async with self.database.sessions() as session:
            existing = await session.scalar(
                select(CreationSource).where(
                    CreationSource.user_id == user_id,
                    CreationSource.canonical_url == canonical,
                )
            )
            if existing is not None:
                return None
            if fingerprint:
                rows = (
                    await session.scalars(
                        select(CreationSource).where(
                            CreationSource.user_id == user_id,
                            CreationSource.trashed_at.is_(None),
                        )
                    )
                ).all()
                for row in rows:
                    if row.fingerprint and adapters.is_duplicate(row.fingerprint, fingerprint):
                        return None
            source = CreationSource(
                user_id=user_id,
                job_id=job.id,
                project_id=job.project_id,
                url=url,
                canonical_url=canonical,
                domain=adapters.domain_of(canonical),
                title=data.get("title") or item.get("title") or "",
                author=data.get("author"),
                published_at=data.get("published"),
                language=data.get("language") or job.language,
                kind="note" if engine_id == "xiaohongshu" else "article",
                engine=engine_id,
                excerpt=adapters.excerpt_of(text) or item.get("snippet", ""),
                content_text=text,
                content_length=len(text),
                fingerprint=fingerprint,
                credibility=score,
                factors=factors,
                metrics=data.get("metrics") or {},
                tags=data.get("tags") or [],
            )
            session.add(source)
            await session.commit()
            return {
                "id": source.id,
                "title": source.title,
                "domain": source.domain,
                "credibility": source.credibility,
            }

    # -- maintenance -------------------------------------------------------
    async def _maintenance_loop(self) -> None:
        from ...admin.creation_config import load_config
        from ..maintenance import cleanup_creation_data

        while True:
            try:
                async with self.database.sessions() as session:
                    config = await load_config(session)
                await cleanup_creation_data(
                    self.database,
                    retention_days=int(config.get("retentionDays") or 30),
                    trash_days=int(config.get("trashDays") or 10),
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                logger.exception("Creation cleanup failed")
            await asyncio.sleep(max(3600, int(timedelta(hours=12).total_seconds())))

    # -- public helpers for tests -----------------------------------------
    async def cleanup_now(self) -> dict[str, int]:
        from ...admin.creation_config import load_config
        from ..maintenance import cleanup_creation_data

        async with self.database.sessions() as session:
            config = await load_config(session)
        return await cleanup_creation_data(
            self.database,
            retention_days=int(config.get("retentionDays") or 30),
            trash_days=int(config.get("trashDays") or 10),
        )


def new_session_id() -> str:
    return f"creation-{uuid4().hex}"


def _payload_preview(payload: Any, limit: int = 240) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]


def _attention_code(attention: dict[str, Any]) -> str:
    reason = str(attention.get("reason") or "").lower()
    return {
        "captcha": "ABM_RESEARCH_CAPTCHA",
        "blocked": "ABM_RESEARCH_BLOCKED",
        "consent_required": "ABM_RESEARCH_CONSENT",
        "login_required": "ABM_RESEARCH_LOGIN_REQUIRED",
    }.get(reason, "ABM_RESEARCH_ATTENTION")


def _payload_error(payload: Any) -> dict[str, str] | None:
    parsed = adapters.parse_tool_result(payload)
    if isinstance(parsed, dict):
        return _tool_error(parsed)
    return None


def _tool_error(parsed: dict[str, Any]) -> dict[str, str] | None:
    error = parsed.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        code = str(error.get("code") or "").strip()
        if message or code:
            return {
                "code": code or "ABM_RESEARCH_TOOL_ERROR",
                "message": message or "The browser tool returned an error.",
            }
    if isinstance(error, str) and error.strip():
        return {"code": "ABM_RESEARCH_TOOL_ERROR", "message": error.strip()[:300]}
    if parsed.get("status") == "error":
        return {
            "code": "ABM_RESEARCH_TOOL_ERROR",
            "message": str(parsed.get("message") or "The browser tool returned an error.")[:300],
        }
    return None


__all__ = [
    "BrowserDriver",
    "GatewayDriver",
    "ResearchRunner",
    "TERMINAL_STATUSES",
    "new_session_id",
]
