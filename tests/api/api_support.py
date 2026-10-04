"""RECONSTRUCTED FILE. The original was untracked and I destroyed it with a
careless `git mv` + heredoc while splitting conftests into uniquely-named
support modules; `git mv` failed because the file was new, but the heredoc still
overwrote it. Recovered from the authoring agent's transcript (one Write plus one
Edit, replayed in order) back to the original 377 lines, then repaired where the
replay lost the secret_root override handling. Recorded here rather than left to
look pristine.

Fixtures for the HTTP surface (RX-42, RX-45, RX-47, RX-53).

EVERYTHING HERE IS THE REAL CODE PATH EXCEPT THE THREE THINGS THAT CANNOT BE.

The application is built by the real :func:`retrace_api.web.app.create_app`, the
real routers are mounted, the real dependency gate runs, and the real admission
and promotion code executes. Three collaborators are substituted, each for a
stated reason:

* the membership directory is :class:`InMemoryMembershipDirectory`, because the
  production directory is unimplemented. It decides authorisation, so the tests
  below prove the authorisation LOGIC and prove nothing about where real
  memberships come from;
* the repository is :class:`InMemoryRepository`, because the unit suite must run
  without PostgreSQL. It reproduces the tenant-scoping SHAPE and none of the
  database behaviour - row-level security is proven in ``tests/postgres`` and in
  the integration test in ``test_tenant_context.py``, never here;
* the clock is deterministic, so an expiry assertion can be exact rather than
  loose.

WHY THE CLIENT TALKS HTTPS.

``cookie_secure`` defaults to ``True`` and the tests keep that default, so the
session cookie is only sent back over a secure scheme. A client on ``http://``
would silently drop it and every authenticated test would fail as
``SESSION_REQUIRED`` - which looks like an authorisation bug and is actually a
fixture one. The base URL is therefore ``https://testserver``.

WHY A SMALL ADMISSION POLICY.

``max_upload_bytes`` is 4096 here rather than 32 MiB. The oversize refusal has
to be exercised through the real route, and a 32 MiB request body would be slow
and would make the test's own memory use the thing under test. The policy is
real; only the numbers are small, and the ``ServiceState`` guard that keeps the
request ceiling above the admission cap still applies.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import pathlib
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from retrace_api.web.admission import AdmissionPolicy
from retrace_api.web.app import create_app
from retrace_api.web.config import CSRF_HEADER_NAME, IDEMPOTENCY_HEADER_NAME, ApiConfig
from retrace_api.web.identity import (
    InMemoryMembershipDirectory,
    Principal,
    SessionRecord,
    SessionStore,
    WorkspaceRole,
)
from retrace_api.web.repository import InMemoryRepository
from retrace_api.web.state import ServiceState
from retrace_api.web.workspace import WorkspaceFactory

REPO = pathlib.Path(__file__).resolve().parents[2]

#: A fixed instant. Every timestamp in these tests derives from it.
START = dt.datetime(2026, 10, 4, 12, 0, 0, tzinfo=dt.UTC)

#: Two tenants, so "the other tenant" is always available without inventing one
#: mid-test. UUIDs because ``TenantWorkspace`` and the RLS predicate both
#: require them.
TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"

#: Subjects. Named by role so a failing assertion reads as a sentence.
OWNER = "oidc|owner"
MEMBER = "oidc|member"
VIEWER = "oidc|viewer"
APPROVER = "oidc|approver"
OUTSIDER = "oidc|outsider"
TENANT_B_MEMBER = "oidc|b-member"

#: A real notebook, long enough that its ``nbformat`` key sits beyond the
#: 512-byte sniff prefix - which is where every real notebook puts it, and the
#: case that used to be refused.
def notebook_bytes(*, cells: int = 8) -> bytes:
    """A syntactically real notebook document.

    Not a stub: the key order is the one every notebook writer produces
    (``cells`` first, ``nbformat`` last), which is the property the admission
    sniff has to cope with.
    """
    document = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [f"# cell {index}\n", "mean_body_mass = 4207.0572\n"],
            }
            for index in range(cells)
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(document, indent=1).encode("utf-8")


CSV_BYTES = b"species,mass_g\nAdelie,3700\nGentoo,5000\nChinstrap,3733\n"


def legitimate_archive() -> bytes:
    """A notebook and a CSV in a zip: the payload admission must ADMIT.

    Present so every refusal below is shown to be discriminating. A gate that
    refuses everything refuses a bomb too and establishes nothing.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("analysis.ipynb", notebook_bytes(cells=2))
        archive.writestr("data/penguins.csv", CSV_BYTES.decode("utf-8"))
    return buffer.getvalue()


def sha256_hex(seed: str) -> str:
    """A genuine digest for a fixture value, never ``'a' * 64``."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def draft_payload(*, project_id: str, created_by: str, version: int = 1) -> dict[str, Any]:
    """A valid ``ResultContractDraft`` body (RX-03, RX-47).

    ``reference_kind`` is ``NEW_TEACHING_REFERENCE``: the fixture data is
    synthetic, so there is no identified prior published evidence, and it is not
    ``NO_REFERENCE`` either because an explicit baseline is declared. The
    matching limitation says so.
    """
    return {
        "project_id": project_id,
        "version": version,
        "reference_kind": "NEW_TEACHING_REFERENCE",
        "inputs": [
            {
                "id": "data/penguins.csv",
                "sha256": sha256_hex("penguins-reference-input"),
                "role": "raw-measurements",
            }
        ],
        "output_definitions": [
            {
                "name": "mean_body_mass",
                "kind": "SCALAR",
                "unit": "g",
                "dtype": "float64",
            }
        ],
        "population": {
            "expected_count": 3,
            "selection_rule": "rows with no missing measurement column",
        },
        "units": {"mean_body_mass": "g"},
        "exclusions": [],
        "seed": 20261004,
        "comparison": {
            "algorithm": "elementwise-abs-rel",
            "tolerances": {"mean_body_mass": {"abs_tol": 1e-6, "rel_tol": 1e-9}},
        },
        "required_checks": ["chk.mean-body-mass"],
        "limitations": [
            "SYNTHETIC fixture data; establishes nothing about any published dataset.",
            "No execution has occurred; the run endpoint is gated by threat T2.",
        ],
        "created_by": created_by,
    }


class Clock:
    """A clock a test can move, so an expiry assertion can be exact."""

    def __init__(self, now: dt.datetime = START) -> None:
        self._now = now

    def __call__(self) -> dt.datetime:
        return self._now

    def advance(self, seconds: float) -> dt.datetime:
        self._now = self._now + dt.timedelta(seconds=seconds)
        return self._now


@dataclass
class Harness:
    """One application, its state, and the helpers a request needs."""

    app: FastAPI
    client: TestClient
    state: ServiceState
    directory: InMemoryMembershipDirectory
    clock: Clock
    storage_root: pathlib.Path
    secret_root: pathlib.Path
    sessions: dict[str, SessionRecord] = field(default_factory=dict)

    def sign_in(self, subject: str, *, display_name: str = "") -> SessionRecord:
        """Establish a session SERVER-SIDE and put its cookies on the client.

        ``SessionStore.establish`` is not reachable from any route, which is the
        property that stops an unauthenticated caller minting its own session.
        A test therefore has to do what an identity-provider callback would.
        """
        record = self.state.sessions.establish(
            Principal(subject=subject, display_name=display_name), now=self.clock()
        )
        self.sessions[subject] = record
        self.client.cookies.set("retrace_session", record.session_id)
        self.client.cookies.set("retrace_csrf", record.csrf_token)
        return record

    def sign_out(self) -> None:
        """Drop the client's cookies without destroying the server record."""
        self.client.cookies.clear()

    def headers(self, subject: str, *, key: str | None = None) -> dict[str, str]:
        """CSRF and idempotency headers for a mutation by ``subject``."""
        record = self.sessions[subject]
        return {
            CSRF_HEADER_NAME: record.csrf_token,
            IDEMPOTENCY_HEADER_NAME: key or str(uuid.uuid4()),
        }

    def create_project(self, tenant: str, subject: str, name: str = "penguins") -> str:
        """Create a project through the real route and return its identifier."""
        response = self.client.post(
            f"/v1/workspaces/{tenant}/projects",
            json={"name": name},
            headers=self.headers(subject),
        )
        assert response.status_code == 201, response.text
        return str(response.json()["project_id"])

    def upload(
        self,
        tenant: str,
        subject: str,
        project_id: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
    ):
        """Post one upload through the real admission route."""
        return self.client.post(
            f"/v1/workspaces/{tenant}/projects/{project_id}/uploads",
            files={"file": (filename, data, content_type)},
            headers=self.headers(subject),
        )


def build_config(
    storage_root: pathlib.Path,
    secret_root: pathlib.Path,
    **overrides: Any,
) -> ApiConfig:
    """An :class:`ApiConfig` with the production defaults kept.

    ``cookie_secure`` stays ``True`` and ``cors_allowed_origins`` stays empty:
    both are properties under test, and a fixture that relaxed them would make
    the tests pass for a configuration nobody ships.
    """
    settings: dict[str, Any] = {
        "storage_root": storage_root,
        "schema_root": REPO / "specs" / "schemas",
        "secret_root": secret_root,
        "max_request_body_bytes": 1024 * 1024,
    }
    settings.update(overrides)
    return ApiConfig(**settings)


def build_state(config: ApiConfig, clock: Clock, directory: InMemoryMembershipDirectory):
    """Wire a :class:`ServiceState` the way production does, minus the database."""
    return ServiceState(
        config=config,
        sessions=SessionStore(
            ttl_seconds=config.session_ttl_seconds, max_sessions=config.max_sessions
        ),
        directory=directory,
        repository=InMemoryRepository(),
        workspaces=WorkspaceFactory(config.storage_root),
        admission_policy=AdmissionPolicy(
            max_upload_bytes=4096,
            max_archive_members=16,
            max_archive_member_bytes=2048,
            max_archive_total_bytes=8192,
            max_compression_ratio=20.0,
        ),
        clock=clock,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def directory() -> InMemoryMembershipDirectory:
    """Memberships for the two fixture tenants.

    Granted server-side, which is the only way a membership is ever created: no
    route reaches :meth:`InMemoryMembershipDirectory.grant`.
    """
    d = InMemoryMembershipDirectory()
    d.grant(OWNER, TENANT_A, WorkspaceRole.ADMIN)
    d.grant(MEMBER, TENANT_A, WorkspaceRole.MEMBER)
    d.grant(VIEWER, TENANT_A, WorkspaceRole.VIEWER)
    d.grant(APPROVER, TENANT_A, WorkspaceRole.APPROVER)
    d.grant(TENANT_B_MEMBER, TENANT_B, WorkspaceRole.ADMIN)
    # OUTSIDER is granted nothing, on purpose.
    return d


@pytest.fixture
def make_harness(
    tmp_path: pathlib.Path, clock: Clock, directory: InMemoryMembershipDirectory
) -> Iterator[Any]:
    """Build a harness, optionally overriding configuration.

    A factory rather than a parametrised fixture because several tests need two
    DIFFERENTLY configured applications in one test - an origin allowlist versus
    none, a configured confinement declaration versus an absent one - and
    comparing them is the assertion.
    """
    clients: list[TestClient] = []
    counter = 0

    def _make(**overrides: Any) -> Harness:
        nonlocal counter
        counter += 1
        storage_root = tmp_path / f"storage-{counter}"
        storage_root.mkdir()
        # A caller may override secret_root - including to None, which is how a
        # test expresses an UNCONFIGURED deployment. So honour the override
        # verbatim and only provision a directory when none was given, rather
        # than passing two values for the same parameter. (Repaired while
        # reconstructing this file - see the note at the top of the module.)
        if "secret_root" in overrides:
            secret_root = overrides.pop("secret_root")
        else:
            secret_root = tmp_path / f"secrets-{counter}"
            secret_root.mkdir()
            (secret_root / "database.password").write_text(
                "fixture-only-not-a-credential\n"
            )
        config = build_config(storage_root, secret_root, **overrides)
        state = build_state(config, clock, directory)
        app = create_app(state)
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Harness(
            app=app,
            client=client,
            state=state,
            directory=directory,
            clock=clock,
            storage_root=storage_root,
            secret_root=secret_root,
        )

    try:
        yield _make
    finally:
        for client in clients:
            client.__exit__(None, None, None)


@pytest.fixture
def harness(make_harness: Any) -> Harness:
    harness: Harness = make_harness()
    return harness
