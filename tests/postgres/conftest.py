"""Fixtures for PostgreSQL-specific tests.

These tests run against a DISPOSABLE PostgreSQL instance (infra/docker-compose.yml).
They are skipped - never silently passed - when it is unreachable, because SQLite
cannot demonstrate row-level security and must not stand in for it.
"""

from __future__ import annotations

import os
import pathlib

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed")

REPO = pathlib.Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = REPO / ".env"
    if envfile.is_file():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update(
        {
            k: v
            for k, v in os.environ.items()
            if k.startswith(("RETRACE_", "POSTGRES_"))
        }
    )
    return env


def _dsn(user_key: str, pw_key: str) -> str:
    e = _env()
    port = e.get("RETRACE_PG_PORT", "5440")
    pw = e.get(pw_key)
    if not pw:
        pytest.skip(f"{pw_key} not set")
    return f"host=127.0.0.1 port={port} dbname=retrace user={user_key} password={pw}"


@pytest.fixture(scope="session")
def svc_dsn() -> str:
    """The APPLICATION role: NOSUPERUSER, NOBYPASSRLS, owns nothing."""
    return _dsn("retrace_svc", "RETRACE_SVC_PASSWORD")


@pytest.fixture(scope="session")
def owner_dsn() -> str:
    """The bootstrap/owner role. Used ONLY to seed fixtures and to prove
    discrimination - never to demonstrate that isolation works."""
    return _dsn("retrace_app", "POSTGRES_PASSWORD")


@pytest.fixture(scope="session", autouse=True)
def _require_postgres(owner_dsn: str):
    try:
        with psycopg.connect(owner_dsn, connect_timeout=5) as c:
            c.execute("select 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"disposable PostgreSQL unreachable: {exc}")
