from sqlalchemy import select

from abm_server.accounts import initialize_identity_state
from abm_server.api_keys import create_api_key
from abm_server.config import Settings
from abm_server.database import Database
from abm_server.models import PlanCode, User
from abm_server.usage import UsageService
from abm_server.usage.quotas import quota_status


async def test_daily_usage_aggregates_tool_calls_and_video(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'usage.db'}",
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="admin-password-123",
        session_cookie_secure=False,
    )
    database = Database(settings)
    await database.create_schema()
    try:
        async with database.sessions() as session:
            await initialize_identity_state(session, settings)
        async with database.sessions() as session:
            user = await session.scalar(select(User).where(User.email == "admin@example.com"))
            assert user is not None
            key, _ = await create_api_key(
                session,
                user=user,
                name="usage",
                settings=settings,
            )
            await session.commit()
            user_id = user.id
            key_id = key.id

        service = UsageService(database)
        await service.record_tool_call(user_id=user_id, api_key_id=key_id)
        await service.record_tool_call(user_id=user_id, api_key_id=key_id)
        await service.record_video(
            user_id=user_id,
            api_key_id=key_id,
            relayed_bytes=1024,
        )

        summary = await service.summary(user_id, days=30)
        assert summary["totals"] == {
            "toolCalls": 2,
            "videoJobs": 1,
            "videoBytes": 1024,
        }
        assert summary["byKey"] == [
            {
                "apiKeyId": key_id,
                "toolCalls": 2,
                "videoJobs": 1,
                "videoBytes": 1024,
            }
        ]
        assert len(summary["daily"]) == 1
        assert summary["daily"][0]["toolCalls"] == 2

        settings.quota_tool_calls_free = 1
        settings.quota_enforcement = "hard"
        exceeded = await service.exceeded_metrics(
            user_id=user_id,
            api_key_id=key_id,
            plan=PlanCode.FREE,
            settings=settings,
        )
        assert "tool_calls" in exceeded
        settings.quota_enforcement = "soft"
        assert (
            await service.exceeded_metrics(
                user_id=user_id,
                api_key_id=key_id,
                plan=PlanCode.FREE,
                settings=settings,
            )
            == []
        )
        status = quota_status(
            {"toolCalls": 2, "videoJobs": 0, "videoBytes": 0},
            {"toolCalls": 1, "videoJobs": 10, "videoBytes": 100},
        )
        assert status["toolCalls"]["over"] is True
        assert status["toolCalls"]["percent"] == 200.0

        threshold = await service.crossed_thresholds(
            user_id=user_id,
            api_key_id=key_id,
            plan=PlanCode.FREE,
            settings=settings,
        )
        assert threshold == 100
        assert (
            await service.crossed_thresholds(
                user_id=user_id,
                api_key_id=key_id,
                plan=PlanCode.FREE,
                settings=settings,
            )
            is None
        )
    finally:
        await database.dispose()
