from __future__ import annotations

from abm_server.config import Settings
from abm_server.creation.exports import create_export
from abm_server.creation.layout import parse_blocks, render_wechat
from abm_server.database import Database
from abm_server.models import CreationAsset, CreationAssetVersion, User
from abm_server.storage import LocalStorage

MARKDOWN = """# 标题

第一段，带 **加粗** 和 [外链](https://example.com)。

## 小标题

- 第一条
- 第二条

> 引用一句话

```python
print("hi")
```

| 列 A | 列 B |
| --- | --- |
| 1 | 2 |

![封面](https://example.com/cover.png)
"""


def test_parse_blocks_keeps_structure() -> None:
    blocks = parse_blocks(MARKDOWN)
    types = [block.type for block in blocks]
    assert "heading" in types
    assert "paragraph" in types
    assert types.count("list_item") == 2
    assert "quote" in types
    assert "code" in types
    assert "table" in types
    assert "image" in types

    heading = next(block for block in blocks if block.type == "heading")
    assert heading.level == 1
    assert "标题" in heading.html

    code = next(block for block in blocks if block.type == "code")
    assert "print" in code.text


def test_parse_blocks_disables_raw_html() -> None:
    blocks = parse_blocks('<script>alert("x")</script>\n\n正文')
    rendered = "".join(block.html for block in blocks)
    assert "<script>" not in rendered


def test_wechat_export_uses_inline_styles() -> None:
    html, images = render_wechat("标题", parse_blocks(MARKDOWN))

    assert "<style" not in html
    assert "class=" not in html
    assert "style=" in html
    assert "[图 1]" in html
    assert "上传压缩包里的 image-01" in html
    assert "（https://example.com）" in html
    assert len(images) == 1
    assert images[0]["src"] == "https://example.com/cover.png"


async def _seed(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'layout.db'}",
        session_cookie_secure=False,
        bootstrap_admin_email=None,
        bootstrap_admin_password=None,
        creation_secret_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        media_root=str(tmp_path / "media"),
    )
    database = Database(settings)
    await database.create_schema()
    async with database.sessions() as session:
        user = User(
            email="layout@example.com",
            password_hash="x",
            display_name="Layout",
            status="active",
        )
        session.add(user)
        await session.flush()
        asset = CreationAsset(user_id=user.id, title="导出测试")
        session.add(asset)
        await session.flush()
        version = CreationAssetVersion(
            asset_id=asset.id,
            user_id=user.id,
            version_no=1,
            content_md=MARKDOWN,
        )
        session.add(version)
        await session.flush()
        asset.current_version_id = version.id
        await session.commit()
        return settings, database, user, asset


async def test_create_wechat_export_stores_html(tmp_path) -> None:
    settings, database, user, asset = await _seed(tmp_path)
    storage = LocalStorage(settings.media_root)
    async with database.sessions() as session:
        export = await create_export(
            session,
            settings,
            storage,
            user,
            asset,
            target="wechat_html",
            style_id="default",
            options={},
        )
        await session.commit()

        assert export.status == "ready"
        assert export.file_key
        payload = await storage.get(export.file_key)
        html = payload.decode("utf-8")
        assert "导出测试" in html
        assert "第一段" in html
        assert export.file_bytes == len(payload)
        assert export.files and export.files[0]["index"] == 1
    await database.dispose()
