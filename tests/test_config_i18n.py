from __future__ import annotations

import re
from pathlib import Path

from abm_server.system_config import GROUPS, SPECS

I18N = Path(__file__).resolve().parents[1] / "abm_server" / "web" / "static" / "workspace-i18n.js"


def _english_keys() -> set[str]:
    text = I18N.read_text(encoding="utf-8")
    english = text.split("zh: {", 1)[0]
    return set(re.findall(r'"(config\.[^"]+)":', english))


def test_every_runtime_config_entry_has_english_copy() -> None:
    keys = _english_keys()
    missing: list[str] = []
    for group in GROUPS:
        key = f'config.group.{group["id"]}'
        if key not in keys:
            missing.append(key)
    for spec in SPECS:
        for suffix in ("label", "description"):
            key = f"config.item.{spec.key}.{suffix}"
            if key not in keys:
                missing.append(key)
    assert not missing, f"Missing English config copy: {missing}"


def test_config_copy_does_not_collide_with_workspace_keys() -> None:
    text = I18N.read_text(encoding="utf-8")
    english = text.split("zh: {", 1)[0]
    keys = re.findall(r'"([^"]+)":', english)
    duplicates = {key for key in keys if keys.count(key) > 1}
    assert not duplicates, f"Duplicate i18n keys: {sorted(duplicates)}"
