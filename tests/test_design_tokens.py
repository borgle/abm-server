from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "abm_server" / "web" / "static"
TOKENS_CSS = STATIC / "app.css"
WORKSPACE_CSS = STATIC / "workspace.css"
GUIDE_CSS = STATIC / "guide.css"
LANDING_CSS = STATIC / "landing.css"

REQUIRED_TOKENS = {
    "--text-2xs": "9px",
    "--text-xs": "10px",
    "--text-sm": "11px",
    "--text-md": "12px",
    "--text-base": "13px",
    "--text-lead": "15px",
    "--space-4": "10px",
    "--space-8": "20px",
    "--control-sm": "28px",
    "--control-md": "34px",
    "--control-lg": "40px",
    "--control-xl": "48px",
    "--radius-sm": "8px",
    "--radius-xl": "18px",
}

DISPLAY_MIN_PX = 17


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_design_tokens_are_defined() -> None:
    root = _read(TOKENS_CSS).split("}", 1)[0]
    for token, value in REQUIRED_TOKENS.items():
        assert f"{token}: {value};" in root, f"{token} should be {value}"


def test_workspace_does_not_redeclare_tokens() -> None:
    workspace = _read(WORKSPACE_CSS)
    root = workspace.split("}", 1)[0]
    assert "--control-md" not in root
    assert "--ws-rail" in root


def test_core_components_use_tokens() -> None:
    baseline = _read(WORKSPACE_CSS).split("Design system baseline", 1)[1]

    assert re.search(r"\.ws-btn \{[^}]*min-height: var\(--control-md\)", baseline)
    assert re.search(r"\.ws-btn-small \{[^}]*min-height: var\(--control-sm\)", baseline)
    assert re.search(r"\.ws-input,\s*\.ws-select \{[^}]*min-height: var\(--control-md\)", baseline)
    assert re.search(r"\.ws-card-pad \{ padding: var\(--space-8\); \}", baseline)
    assert re.search(r"\.ws-nav a \{[^}]*min-height: var\(--control-lg\)", baseline)


def test_public_components_use_tokens() -> None:
    css = _read(TOKENS_CSS)
    public = css.split("Public pages", 1)[1]

    assert re.search(r"\.button \{[^}]*min-height: var\(--control-lg\)", public)
    assert re.search(r"\.button\.small \{[^}]*min-height: var\(--control-sm\)", public)
    assert re.search(r"input, textarea, select \{[^}]*min-height: var\(--control-lg\)", public)


def test_text_sizes_stay_on_the_scale() -> None:
    """Body text must use tokens; only display sizes may stay literal."""

    offenders: list[str] = []
    for path in (WORKSPACE_CSS, TOKENS_CSS, GUIDE_CSS, LANDING_CSS):
        for line_number, line in enumerate(_read(path).splitlines(), 1):
            for match in re.finditer(r"font-size:\s*([^;]+);", line):
                value = match.group(1).replace("!important", "").strip()
                if value.startswith("var(") or value.startswith("clamp("):
                    continue
                size = re.fullmatch(r"(\d+(?:\.\d+)?)px", value)
                if size and float(size.group(1)) >= DISPLAY_MIN_PX:
                    continue
                if re.fullmatch(r"[\d.]+(em|rem|%)", value):
                    continue
                offenders.append(f"{path.name}:{line_number}: {line.strip()}")
    assert not offenders, f"Off-scale font sizes: {offenders}"
