"""Deployment editions.

The open-source distribution ships the ``single`` edition only. The hosted
edition is delivered as a private package and is not part of the public source
tree; this module intentionally exposes capabilities, not implementations.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from fastapi import Request

from .errors import ApiError


@dataclass(frozen=True, slots=True)
class Edition:
    name: str
    multi_user: bool
    self_registration: bool
    plans: bool
    approvals: bool
    audit: bool
    admin_users: bool
    billing: bool

    def capability(self, name: str) -> bool:
        return bool(getattr(self, name, False))


SINGLE = Edition(
    name="single",
    multi_user=False,
    self_registration=False,
    plans=False,
    approvals=False,
    audit=False,
    admin_users=False,
    billing=False,
)

HOSTED = Edition(
    name="hosted",
    multi_user=True,
    self_registration=True,
    plans=True,
    approvals=True,
    audit=True,
    admin_users=True,
    billing=True,
)

EDITIONS = {"single": SINGLE, "hosted": HOSTED}


def resolve_edition(name: str) -> Edition:
    key = (name or "hosted").strip().lower()
    edition = EDITIONS.get(key)
    if edition is None:
        raise RuntimeError(
            f"Unknown ABM_EDITION {name!r}; expected one of {sorted(EDITIONS)}"
        )
    if edition.multi_user and importlib.util.find_spec("abm_cloud") is None:
        raise RuntimeError(
            "ABM_EDITION=hosted requires the private abm_cloud package. "
            "The open-source build only supports ABM_EDITION=single."
        )
    return edition


def require_capability(name: str):
    """Reject routes that do not exist in the current edition."""

    async def dependency(request: Request) -> None:
        edition = getattr(request.app.state, "edition", HOSTED)
        if not edition.capability(name):
            raise ApiError(404, "ABM_NOT_FOUND", "Not found.")

    return dependency
