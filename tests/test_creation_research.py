from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from sqlalchemy import func, select

from abm_server.config import Settings
from abm_server.creation.maintenance import cleanup_creation_data
from abm_server.creation.research import adapters
from abm_server.creation.research.planner import build_plan, pages_for_depth
from abm_server.creation.research.runner import ResearchRunner
from abm_server.creation.research.service import create_job
from abm_server.database import Database
from abm_server.extension_gateway import GatewayCallError
from abm_server.models import (
    CreationAsset,
    CreationAssetVersion,
    CreationJobEvent,
    CreationResearchJob,
    CreationSource,
    User,
    utcnow,
)


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'research.db'}",
        session_cookie_secure=False,
        bootstrap_admin_email=None,
        bootstrap_admin_password=None,
        creation_secret_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        **overrides,
    )


async def _seed_user(database: Database, email: str = "user@example.com") -> User:
    async with database.sessions() as session:
        user = User(
            email=email,
            password_hash="not-used",
            display_name="Researcher",
            role="user",
            status="active",
            plan_code="free",
        )
        session.add(user)
        await session.commit()
        return user


def _tool(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


class FakeDriver:
    def __init__(self, *, attention: dict | None = None) -> None:
        self.attention = attention
        self.navigations: list[str] = []
        self.counter = 0

    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        self.navigations.append(url)
        return {}

    async def extract(self, script: str, args: dict) -> dict:
        self.counter += 1
        if script is adapters.SEARCH_SCRIPT:
            if self.attention:
                return _tool({"results": [], "needsAttention": self.attention})
            return _tool(
                {
                    "results": [
                        {
                            "title": f"Result {self.counter}",
                            "url": f"https://example.com/article-{self.counter}",
                            "snippet": "A useful explanation.",
                        },
                        {
                            "title": f"Second {self.counter}",
                            "url": f"https://example.org/second-{self.counter}",
                            "snippet": "Another angle.",
                        },
                    ],
                    "needsAttention": None,
                }
            )
        return _tool(
            {
                "title": "Example article",
                "url": "",
                "canonical": "",
                "author": "Ada",
                "published": "2026-01-02",
                "language": "en",
                "text": f"Useful content number {self.counter} about a distinct topic. " * 40,
                "needsAttention": None,
            }
        )


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def acquire_connection_for_session(self, **_kwargs):
        return "conn_test"

    async def release_session(self, *_args, **_kwargs) -> None:
        return None

    async def call_tool(self, *, name: str, arguments: dict, **_kwargs):
        self.calls.append(name)
        if name == "browser_navigate":
            return _tool({"success": True, "tabId": 42})
        if name == "browser_wait_elements":
            assert arguments.get("tabId") == 42
            return _tool({"success": True, "actualCount": 1})
        if name == "browser_inject_script":
            assert arguments.get("tabId") == 42
            if arguments.get("code") == adapters.SEARCH_SCRIPT:
                return _tool(
                    {
                        "results": [
                            {
                                "title": "Gateway result",
                                "url": "https://example.com/gateway-result",
                                "snippet": "Collected through the gateway.",
                            }
                        ],
                        "needsAttention": None,
                    }
                )
            return _tool(
                {
                    "title": "Gateway article",
                    "url": "",
                    "canonical": "",
                    "author": "Ada",
                    "published": "2026-01-02",
                    "language": "en",
                    "text": "Gateway article content with citations. " * 60,
                    "needsAttention": None,
                }
            )
        raise AssertionError(f"unexpected tool {name}")


def test_planner_builds_queries_and_page_budget() -> None:
    plan = build_plan(["收纳"], ["广告"], ["bing", "google"], "quick")
    assert 2 <= len(plan) <= 6
    assert plan[0]["query"] == "收纳 -广告"
    assert plan[0]["engines"] == ["bing", "google"]
    assert pages_for_depth("quick") == 10
    assert pages_for_depth("deep") == 80
    assert build_plan([], [], ["bing"], "quick") == []


def test_url_normalization_and_fingerprints() -> None:
    assert (
        adapters.normalize_url("HTTPS://WWW.Example.com/a/?utm_source=x&b=2&a=1#top")
        == "https://example.com/a?a=1&b=2"
    )
    assert adapters.normalize_url("not a url") == ""
    assert (
        adapters.normalize_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x")
        == "https://example.com/a"
    )
    first = adapters.fingerprint_text("同一个来源的正文内容会得到稳定的指纹。" * 5)
    second = adapters.fingerprint_text("同一个来源的正文内容会得到稳定的指纹。" * 5)
    other = adapters.fingerprint_text("完全不同的另一篇文章，讨论别的主题。" * 5)
    assert first == second
    assert adapters.is_duplicate(first, second)
    assert not adapters.is_duplicate(first, other)


def test_credibility_factors_are_explainable() -> None:
    score, factors = adapters.score_credibility(
        url="https://www.gov.cn/zhengce/content.html",
        author="Author",
        published="2026-01-01",
        text="Official text with sources http://a http://b http://c " * 60,
    )
    assert 0 <= score <= 100
    assert set(factors) == {"domain", "author", "freshness", "references", "completeness"}
    assert factors["domain"] > 20


def test_runner_collects_sources_and_events(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        runner = ResearchRunner(database, gateway=None, settings=_settings(tmp_path))
        user = await _seed_user(database)
        async with database.sessions() as session:
            job = await create_job(
                session,
                user,
                keywords=["收纳"],
                engines=["bing"],
                depth="quick",
                config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
            )
            await session.commit()
            job_id = job.id

        driver = FakeDriver()
        await runner.run_job(job_id, driver=driver)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status in {"completed", "partial"}
            assert job.pages_collected >= 2
            source_count = await session.scalar(
                select(func.count(CreationSource.id)).where(CreationSource.user_id == user.id)
            )
            assert source_count == job.pages_collected
            events = (
                await session.scalars(
                    select(CreationJobEvent)
                    .where(CreationJobEvent.job_id == job_id)
                    .order_by(CreationJobEvent.seq)
                )
            ).all()
            types = [event.data.get("type") for event in events]
            assert "job.started" in types
            assert "source.saved" in types
            assert types[-1] == "job.finished"
            assert [event.seq for event in events] == list(range(1, len(events) + 1))
        await database.dispose()

    asyncio.run(scenario())


def test_runner_uses_contiguous_event_sequence_with_gateway(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        gateway = FakeGateway()
        runner = ResearchRunner(database, gateway=gateway, settings=_settings(tmp_path))
        user = await _seed_user(database)
        async with database.sessions() as session:
            job = await create_job(
                session,
                user,
                keywords=["收纳"],
                engines=["bing"],
                depth="quick",
                config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
            )
            await session.commit()
            job_id = job.id

        await runner.run_job(job_id)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status in {"completed", "partial"}
            events = (
                await session.scalars(
                    select(CreationJobEvent)
                    .where(CreationJobEvent.job_id == job_id)
                    .order_by(CreationJobEvent.seq)
                )
            ).all()
            types = [event.data.get("type") for event in events]
            assert types[0] == "connection.acquired"
            assert types[1] == "job.started"
            assert [event.seq for event in events] == list(range(1, len(events) + 1))
        await database.dispose()

    asyncio.run(scenario())


def test_runner_marks_login_wall_as_needs_attention(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        runner = ResearchRunner(database, gateway=None, settings=_settings(tmp_path))
        user = await _seed_user(database)
        async with database.sessions() as session:
            job = await create_job(
                session,
                user,
                keywords=["收纳"],
                engines=["xiaohongshu"],
                depth="quick",
                config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
            )
            await session.commit()
            job_id = job.id

        driver = FakeDriver(attention={"reason": "login_required", "message": "Please sign in."})
        await runner.run_job(job_id, driver=driver)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status == "needs_attention"
            assert job.attention["reason"] == "login_required"
            events = (
                await session.scalars(
                    select(CreationJobEvent)
                    .where(CreationJobEvent.job_id == job_id)
                    .order_by(CreationJobEvent.seq)
                )
            ).all()
            assert events[-1].data["type"] == "attention.required"
        await database.dispose()

    asyncio.run(scenario())


def test_runner_reports_offline_extension(tmp_path) -> None:
    class OfflineGateway:
        async def acquire_connection_for_session(self, **_kwargs):
            raise GatewayCallError(
                "ABM_EXTENSION_OFFLINE",
                "No online browser extension is available.",
                retryable=True,
                action="open_extension",
            )

        async def release_session(self, *_args, **_kwargs) -> None:
            return None

    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        runner = ResearchRunner(database, gateway=OfflineGateway(), settings=_settings(tmp_path))
        user = await _seed_user(database)
        async with database.sessions() as session:
            job = await create_job(
                session,
                user,
                keywords=["收纳"],
                engines=["bing"],
                depth="quick",
                config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
            )
            await session.commit()
            job_id = job.id

        await runner.run_job(job_id)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status == "needs_attention"
            assert job.attention["reason"] == "extension_offline"
        await database.dispose()

    asyncio.run(scenario())


def test_cleanup_moves_sources_to_trash_then_purges(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        user = await _seed_user(database)
        old = utcnow() - timedelta(days=40)
        async with database.sessions() as session:
            session.add(
                CreationSource(
                    user_id=user.id,
                    url="https://example.com/old",
                    canonical_url="https://example.com/old",
                    domain="example.com",
                    title="Old source",
                    fetched_at=old,
                )
            )
            await session.commit()

        result = await cleanup_creation_data(database, retention_days=30, trash_days=10)
        assert result["trashedSources"] == 1

        async with database.sessions() as session:
            source = await session.scalar(select(CreationSource))
            assert source is not None
            assert source.trashed_at is not None
            assert source.trash_reason == "expired"
            purge_after = source.purge_after

        result = await cleanup_creation_data(
            database,
            retention_days=30,
            trash_days=10,
            now=purge_after + timedelta(days=1),
        )
        assert result["purgedSources"] == 1
        async with database.sessions() as session:
            assert await session.scalar(select(func.count(CreationSource.id))) == 0
        await database.dispose()

    asyncio.run(scenario())


def test_cleanup_purges_trashed_assets_with_versions(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        user = await _seed_user(database)
        async with database.sessions() as session:
            asset = CreationAsset(
                user_id=user.id,
                title="Trashed",
                trashed_at=utcnow() - timedelta(days=11),
                purge_after=utcnow() - timedelta(days=1),
                trash_reason="manual",
            )
            session.add(asset)
            await session.flush()
            session.add(
                CreationAssetVersion(
                    asset_id=asset.id,
                    user_id=user.id,
                    version_no=1,
                    content_md="hello",
                )
            )
            await session.commit()

        result = await cleanup_creation_data(database, retention_days=30, trash_days=10)
        assert result["purgedAssets"] == 1
        async with database.sessions() as session:
            assert await session.scalar(select(func.count(CreationAsset.id))) == 0
            assert await session.scalar(select(func.count(CreationAssetVersion.id))) == 0
        await database.dispose()

    asyncio.run(scenario())


class TimeoutDriver:
    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        return {}

    async def extract(self, script: str, args: dict) -> dict:
        raise GatewayCallError(
            "ABM_TOOL_TIMEOUT",
            "Tool browser_inject_script did not return a result within 30000ms.",
            retryable=True,
        )


class MalformedDriver:
    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        return {}

    async def extract(self, script: str, args: dict) -> dict:
        return {"content": [{"type": "text", "text": "not json"}]}


class EmptyDriver:
    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        return {}

    async def extract(self, script: str, args: dict) -> dict:
        return _tool({"results": [], "title": "????", "needsAttention": None})


class ErrorPayloadDriver:
    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        return {}

    async def extract(self, script: str, args: dict) -> dict:
        return _tool(
            {
                "error": {
                    "code": "ABM_TOOL_EXECUTION_FAILED",
                    "message": "Cannot access the current tab.",
                }
            }
        )


async def _run_with(driver, tmp_path):
    database = Database(_settings(tmp_path))
    await database.create_schema()
    runner = ResearchRunner(database, gateway=None, settings=_settings(tmp_path))
    user = await _seed_user(database)
    async with database.sessions() as session:
        job = await create_job(
            session,
            user,
            keywords=["??"],
            engines=["bing"],
            depth="quick",
            config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
        )
        await session.commit()
        job_id = job.id
    await runner.run_job(job_id, driver=driver)
    async with database.sessions() as session:
        job = await session.get(CreationResearchJob, job_id)
        events = (
            await session.scalars(
                select(CreationJobEvent)
                .where(CreationJobEvent.job_id == job_id)
                .order_by(CreationJobEvent.seq)
            )
        ).all()
    await database.dispose()
    return job, events


def test_runner_reports_tool_timeout_with_reason(tmp_path) -> None:
    job, events = asyncio.run(_run_with(TimeoutDriver(), tmp_path))
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "ABM_TOOL_TIMEOUT"
    assert "browser_inject_script" in (job.error_message or "")
    assert job.progress["lastError"]["code"] == "ABM_TOOL_TIMEOUT"
    assert any(event.data.get("type") == "search.failed" for event in events)


def test_runner_reports_malformed_payload(tmp_path) -> None:
    job, _events = asyncio.run(_run_with(MalformedDriver(), tmp_path))
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "ABM_RESEARCH_BAD_PAYLOAD"
    assert job.progress["lastError"]["step"] == "search"


def test_runner_reports_empty_search_results(tmp_path) -> None:
    job, _events = asyncio.run(_run_with(EmptyDriver(), tmp_path))
    assert job is not None
    assert job.status == "partial"
    assert job.error_code == "ABM_RESEARCH_NO_RESULTS"
    assert "no parsable results" in (job.error_message or "").lower()


def test_runner_surfaces_tool_error_payload(tmp_path) -> None:
    job, _events = asyncio.run(_run_with(ErrorPayloadDriver(), tmp_path))
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "ABM_TOOL_EXECUTION_FAILED"
    assert "Cannot access" in (job.error_message or "")


def test_runner_reports_busy_connection(tmp_path) -> None:
    class BusyGateway:
        async def acquire_connection_for_session(self, **_kwargs):
            raise GatewayCallError(
                "ABM_CONNECTION_BUSY",
                "All browser connections for the current account are in use.",
                retryable=True,
                action="wait",
            )

        async def release_session(self, *_args, **_kwargs) -> None:
            return None

    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        runner = ResearchRunner(database, gateway=BusyGateway(), settings=_settings(tmp_path))
        user = await _seed_user(database)
        async with database.sessions() as session:
            job = await create_job(
                session,
                user,
                keywords=["??"],
                engines=["bing"],
                depth="quick",
                config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
            )
            await session.commit()
            job_id = job.id
        await runner.run_job(job_id)
        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status == "needs_attention"
            assert job.attention["reason"] == "connection_busy"
        await database.dispose()

    asyncio.run(scenario())


class NavigateErrorDriver:
    async def navigate(self, url: str, *, reuse_key: str) -> dict:
        return _tool(
            {
                "error": {
                    "code": "ABM_TOOL_EXECUTION_FAILED",
                    "message": "Tab was closed before navigation finished.",
                }
            }
        )

    async def extract(self, script: str, args: dict) -> dict:
        raise AssertionError("extract should not run after a failed navigation")


def test_runner_reports_navigation_error(tmp_path) -> None:
    job, events = asyncio.run(_run_with(NavigateErrorDriver(), tmp_path))
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "ABM_TOOL_EXECUTION_FAILED"
    assert "Tab was closed" in (job.error_message or "")
    assert any(event.data.get("type") == "search.failed" for event in events)


class CaptchaThenResultsDriver(FakeDriver):
    def __init__(self) -> None:
        super().__init__()
        self.searches = 0

    async def extract(self, script: str, args: dict) -> dict:
        if script is adapters.SEARCH_SCRIPT:
            self.searches += 1
            if self.searches == 1:
                return _tool(
                    {
                        "results": [],
                        "needsAttention": {
                            "reason": "captcha",
                            "message": "The site requires a verification step.",
                        },
                    }
                )
        return await super().extract(script, args)


async def _run_engines(driver, engines, tmp_path, **settings_overrides):
    database = Database(_settings(tmp_path, **settings_overrides))
    await database.create_schema()
    runner = ResearchRunner(
        database, gateway=None, settings=_settings(tmp_path, **settings_overrides)
    )
    user = await _seed_user(database)
    async with database.sessions() as session:
        job = await create_job(
            session,
            user,
            keywords=["??"],
            engines=engines,
            depth="quick",
            config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
        )
        await session.commit()
        job_id = job.id
    await runner.run_job(job_id, driver=driver)
    async with database.sessions() as session:
        job = await session.get(CreationResearchJob, job_id)
    await database.dispose()
    return job


def test_runner_auto_skips_captcha_engine(tmp_path) -> None:
    job = asyncio.run(
        _run_engines(
            FakeDriver(attention={"reason": "captcha", "message": "Verify."}),
            ["bing"],
            tmp_path,
            research_pause_on_interstitial=False,
        )
    )
    assert job is not None
    assert job.status == "partial"
    assert job.error_code == "ABM_RESEARCH_CAPTCHA"
    assert job.progress["skippedEngines"] == ["bing"]


def test_runner_continues_other_engines_after_captcha(tmp_path) -> None:
    job = asyncio.run(
        _run_engines(
            CaptchaThenResultsDriver(),
            ["bing", "duckduckgo"],
            tmp_path,
            research_pause_on_interstitial=False,
        )
    )
    assert job is not None
    assert job.status in {"partial", "completed"}
    assert job.pages_collected >= 1
    assert job.progress["skippedEngines"] == ["bing"]
    assert job.error_code in {"ABM_RESEARCH_PARTIAL", "ABM_RESEARCH_CAPTCHA"}


class ForkingDriver(FakeDriver):
    def __init__(self) -> None:
        super().__init__()
        self.inflight = 0
        self.peak = 0

    def fork(self):  # noqa: ANN201 - test double
        return self

    async def extract(self, script: str, args: dict) -> dict:
        if script is adapters.SEARCH_SCRIPT:
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.05)
            try:
                return await super().extract(script, args)
            finally:
                self.inflight -= 1
        return await super().extract(script, args)


def test_runner_searches_engines_in_parallel(tmp_path) -> None:
    driver = ForkingDriver()
    job = asyncio.run(_run_engines(driver, ["bing", "baidu"], tmp_path))
    assert job is not None
    assert driver.peak >= 2
    assert job.status in {"completed", "partial"}


class CaptchaOnFirstFetchDriver(FakeDriver):
    def __init__(self) -> None:
        super().__init__()
        self.fetches = 0

    async def extract(self, script: str, args: dict) -> dict:
        if script is adapters.SEARCH_SCRIPT:
            return _tool(
                {
                    "results": [
                        {
                            "title": "Captcha page",
                            "url": "https://example.com/protected",
                            "snippet": "Needs verification.",
                        }
                    ],
                    "needsAttention": None,
                }
            )
        self.fetches += 1
        if self.fetches == 1:
            return _tool(
                {
                    "needsAttention": {
                        "reason": "captcha",
                        "message": "Complete the verification step.",
                    }
                }
            )
        return await super().extract(script, args)


async def _captcha_job(tmp_path):
    settings = _settings(tmp_path, research_attention_timeout_seconds=0)
    database = Database(settings)
    await database.create_schema()
    runner = ResearchRunner(database, gateway=None, settings=settings)
    user = await _seed_user(database)
    async with database.sessions() as session:
        job = await create_job(
            session,
            user,
            keywords=["??"],
            engines=["bing"],
            depth="quick",
            config={"enabled": True, "plans": {"free": {"pagesPerMonth": 0}}},
        )
        await session.commit()
        return database, runner, user, job.id


def test_runner_pauses_on_captcha_and_retries_after_resume(tmp_path) -> None:
    async def scenario() -> None:
        database, runner, user, job_id = await _captcha_job(tmp_path)
        driver = CaptchaOnFirstFetchDriver()
        await runner.run_job(job_id, driver=driver)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status == "needs_attention"
            assert job.attention["reason"] == "captcha"
            assert job.attention["url"] == "https://example.com/protected"

        await runner.run_job(job_id, driver=driver)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status == "completed"
            sources = await session.scalar(
                select(func.count(CreationSource.id)).where(CreationSource.user_id == user.id)
            )
            assert sources == 1
        await database.dispose()

    asyncio.run(scenario())


def test_runner_skip_current_marks_url_visited(tmp_path) -> None:
    async def scenario() -> None:
        database, runner, user, job_id = await _captcha_job(tmp_path)
        driver = CaptchaOnFirstFetchDriver()
        await runner.run_job(job_id, driver=driver)

        runner.launch = lambda _job_id: None  # type: ignore[assignment]
        await runner.resume(job_id, skip_current=True)

        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert "https://example.com/protected" in job.progress["visited"]
            assert job.status == "queued"

        await runner.run_job(job_id, driver=driver)
        async with database.sessions() as session:
            job = await session.get(CreationResearchJob, job_id)
            assert job is not None
            assert job.status != "needs_attention"
            sources = await session.scalar(
                select(func.count(CreationSource.id)).where(CreationSource.user_id == user.id)
            )
            assert sources == 0
        await database.dispose()

    asyncio.run(scenario())
