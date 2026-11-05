from pathlib import Path


def test_uvicorn_standard_extra_is_required() -> None:
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"uvicorn[standard]>=0.34,<1"' in pyproject
