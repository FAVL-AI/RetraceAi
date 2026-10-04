"""Tenant-scoped persistence for projects and contracts (RX-47, RX-48, RX-49).

THE TENANT IS A PROPERTY OF THE UNIT OF WORK, NOT AN ARGUMENT TO A QUERY.

Every method below takes the object's own identifier and never a tenant. The
tenant comes from the unit of work, which was opened with the tenant the session
was authorised for. A handler therefore has no way to express "read this row in
that tenant": the parameter does not exist. That is a stronger guarantee than
remembering to pass the right value, and it is what makes "an ordinary edit
cannot move an object between tenants" structural rather than a convention -
``rename_project`` writes ``WHERE tenant_id = <uow tenant>`` and has no
``tenant_id`` parameter at all.

TWO IMPLEMENTATIONS, AND WHAT EACH DOES AND DOES NOT ESTABLISH.

:class:`SqlRepository` is the real one. It opens a transaction, sets
``retrace.tenant_id`` transaction-locally, asserts it, and lets row-level
security confine the statements. It needs PostgreSQL, so the tests that use it
are marked ``integration``.

:class:`InMemoryRepository` exists because the unit suite must run without a
database. It is NOT a stand-in for the RLS proof and is documented as such: it
reproduces the *authorisation shape* (tenant-scoped unit of work, fail-closed on
a missing tenant, real rollback) so the HTTP layer can be tested, and it
reproduces none of the database behaviour. ``tests/postgres`` and
``tests/migrations`` are where isolation is actually demonstrated.

ROLLBACK IS REAL IN BOTH.

The in-memory unit of work stages writes in a private dict and merges them on
successful exit. A handler that raises half way therefore leaves nothing behind
in the unit suite either - otherwise "the transaction rolls back cleanly" would
be a claim tested only where PostgreSQL happens to be available.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Protocol

import sqlalchemy as sa
from retrace_api.web.errors import CrossTenantReferenceRefused, NotFound
from retrace_api.web.tenancy import normalise_tenant_id, tenant_transaction

__all__ = [
    "ContractRecord",
    "InMemoryRepository",
    "ProjectRecord",
    "Repository",
    "SqlRepository",
    "TenantUnitOfWork",
]


@dataclass(frozen=True)
class ProjectRecord:
    """One row of ``projects`` (RX-49)."""

    tenant_id: str
    id: str
    name: str
    created_at: dt.datetime


@dataclass(frozen=True)
class ContractRecord:
    """One row of ``result_contracts`` (RX-49).

    ``approved`` is a denormalised flag maintained from the approval ledger. The
    ledger is the authority; this column exists so a listing does not have to
    replay a hash chain, and nothing reads it to DECIDE whether a contract is
    approved.
    """

    tenant_id: str
    id: str
    project_id: str
    contract_hash: str
    approved: bool


class TenantUnitOfWork(Protocol):
    """Operations available inside one tenant-scoped transaction."""

    @property
    def tenant_id(self) -> str: ...

    def create_project(self, *, project_id: str, name: str, created_at: dt.datetime) -> (
        ProjectRecord
    ): ...

    def get_project(self, project_id: str) -> ProjectRecord | None: ...

    def list_projects(self) -> tuple[ProjectRecord, ...]: ...

    def rename_project(self, project_id: str, name: str) -> ProjectRecord: ...

    def create_contract(
        self, *, contract_id: str, project_id: str, contract_hash: str
    ) -> ContractRecord: ...

    def get_contract(self, contract_id: str) -> ContractRecord | None: ...

    def list_contracts(self, project_id: str | None = None) -> tuple[ContractRecord, ...]: ...

    def mark_contract_approved(self, contract_id: str) -> ContractRecord: ...


class Repository(Protocol):
    """Opens tenant-scoped units of work."""

    def unit_of_work(self, tenant_id: str) -> contextlib.AbstractContextManager[TenantUnitOfWork]:
        ...


def _missing_project(project_id: str) -> NotFound:
    return NotFound(
        f"no project {project_id!r} exists in the authorised workspace",
        remedy="list the workspace's projects and use an identifier from that listing",
    )


def _missing_contract(contract_id: str) -> NotFound:
    return NotFound(
        f"no contract {contract_id!r} exists in the authorised workspace",
        remedy="list the workspace's contracts and use an identifier from that listing",
    )


class _InMemoryUnitOfWork:
    """Staged writes against the in-memory store, merged only on clean exit."""

    def __init__(
        self,
        tenant_id: str,
        projects: dict[tuple[str, str], ProjectRecord],
        contracts: dict[tuple[str, str], ContractRecord],
    ) -> None:
        self._tenant_id = tenant_id
        self._base_projects = projects
        self._base_contracts = contracts
        self._staged_projects: dict[tuple[str, str], ProjectRecord] = {}
        self._staged_contracts: dict[tuple[str, str], ContractRecord] = {}

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def _key(self, object_id: str) -> tuple[str, str]:
        return (self._tenant_id, object_id)

    def commit(self) -> None:
        self._base_projects.update(self._staged_projects)
        self._base_contracts.update(self._staged_contracts)

    def create_project(
        self, *, project_id: str, name: str, created_at: dt.datetime
    ) -> ProjectRecord:
        record = ProjectRecord(
            tenant_id=self._tenant_id, id=project_id, name=name, created_at=created_at
        )
        self._staged_projects[self._key(project_id)] = record
        return record

    def get_project(self, project_id: str) -> ProjectRecord | None:
        key = self._key(project_id)
        return self._staged_projects.get(key) or self._base_projects.get(key)

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        merged = {**self._base_projects, **self._staged_projects}
        return tuple(
            sorted(
                (r for (tenant, _), r in merged.items() if tenant == self._tenant_id),
                key=lambda r: (r.created_at, r.id),
            )
        )

    def rename_project(self, project_id: str, name: str) -> ProjectRecord:
        existing = self.get_project(project_id)
        if existing is None:
            raise _missing_project(project_id)
        # `replace` keeps tenant_id: the field is not a parameter of this method,
        # so an edit cannot move the row to another tenant.
        record = replace(existing, name=name)
        self._staged_projects[self._key(project_id)] = record
        return record

    def create_contract(
        self, *, contract_id: str, project_id: str, contract_hash: str
    ) -> ContractRecord:
        if self.get_project(project_id) is None:
            # RX-49. In PostgreSQL the composite foreign key refuses this; here
            # the parent is checked explicitly so the two layers agree about what
            # is refused rather than one of them being permissive.
            raise CrossTenantReferenceRefused(
                f"project {project_id!r} is not in the authorised workspace, so a "
                "contract cannot reference it",
                remedy="create the contract under a project of this workspace",
            )
        record = ContractRecord(
            tenant_id=self._tenant_id,
            id=contract_id,
            project_id=project_id,
            contract_hash=contract_hash,
            approved=False,
        )
        self._staged_contracts[self._key(contract_id)] = record
        return record

    def get_contract(self, contract_id: str) -> ContractRecord | None:
        key = self._key(contract_id)
        return self._staged_contracts.get(key) or self._base_contracts.get(key)

    def list_contracts(self, project_id: str | None = None) -> tuple[ContractRecord, ...]:
        merged = {**self._base_contracts, **self._staged_contracts}
        rows = [r for (tenant, _), r in merged.items() if tenant == self._tenant_id]
        if project_id is not None:
            rows = [r for r in rows if r.project_id == project_id]
        return tuple(sorted(rows, key=lambda r: r.id))

    def mark_contract_approved(self, contract_id: str) -> ContractRecord:
        existing = self.get_contract(contract_id)
        if existing is None:
            raise _missing_contract(contract_id)
        record = replace(existing, approved=True)
        self._staged_contracts[self._key(contract_id)] = record
        return record


class InMemoryRepository:
    """Process-local store with the same tenant-scoping shape as the SQL one.

    Deliberately not a production component. It carries no row-level security,
    no composite key enforced by a server, and no durability.
    """

    def __init__(self) -> None:
        self._projects: dict[tuple[str, str], ProjectRecord] = {}
        self._contracts: dict[tuple[str, str], ContractRecord] = {}

    @contextlib.contextmanager
    def unit_of_work(self, tenant_id: str) -> Iterator[TenantUnitOfWork]:
        canonical = normalise_tenant_id(tenant_id)
        uow = _InMemoryUnitOfWork(canonical, self._projects, self._contracts)
        yield uow
        uow.commit()

    def rows_for_audit(self) -> tuple[tuple[str, str], ...]:
        """Every (tenant, project) pair, for tests that must look past the API."""
        return tuple(sorted(self._projects))


class _SqlUnitOfWork:
    """Statements issued on a connection whose tenant context is already set."""

    def __init__(self, tenant_id: str, connection: sa.Connection) -> None:
        self._tenant_id = tenant_id
        self._connection = connection
        self._tenant_uuid = uuid.UUID(tenant_id)

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def create_project(
        self, *, project_id: str, name: str, created_at: dt.datetime
    ) -> ProjectRecord:
        self._connection.execute(
            sa.text(
                "INSERT INTO projects (tenant_id, id, name, created_at) "
                "VALUES (:tenant_id, :id, :name, :created_at)"
            ),
            {
                "tenant_id": self._tenant_uuid,
                "id": uuid.UUID(project_id),
                "name": name,
                "created_at": created_at,
            },
        )
        return ProjectRecord(
            tenant_id=self._tenant_id, id=project_id, name=name, created_at=created_at
        )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        try:
            wanted = uuid.UUID(project_id)
        except ValueError:
            return None
        row = self._connection.execute(
            sa.text("SELECT tenant_id, id, name, created_at FROM projects WHERE id = :id"),
            {"id": wanted},
        ).first()
        if row is None:
            return None
        return ProjectRecord(
            tenant_id=str(row[0]), id=str(row[1]), name=row[2], created_at=row[3]
        )

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        rows = self._connection.execute(
            sa.text("SELECT tenant_id, id, name, created_at FROM projects ORDER BY created_at, id")
        ).all()
        return tuple(
            ProjectRecord(tenant_id=str(r[0]), id=str(r[1]), name=r[2], created_at=r[3])
            for r in rows
        )

    def rename_project(self, project_id: str, name: str) -> ProjectRecord:
        try:
            wanted = uuid.UUID(project_id)
        except ValueError as exc:
            raise _missing_project(project_id) from exc
        # No `tenant_id` in the SET clause and none in the parameters: the only
        # rows this statement can reach are the ones the policy already admits,
        # and the only column it can change is the name (RX-47, RX-49).
        row = self._connection.execute(
            sa.text(
                "UPDATE projects SET name = :name WHERE id = :id "
                "RETURNING tenant_id, id, name, created_at"
            ),
            {"name": name, "id": wanted},
        ).first()
        if row is None:
            raise _missing_project(project_id)
        return ProjectRecord(
            tenant_id=str(row[0]), id=str(row[1]), name=row[2], created_at=row[3]
        )

    def create_contract(
        self, *, contract_id: str, project_id: str, contract_hash: str
    ) -> ContractRecord:
        try:
            project_uuid = uuid.UUID(project_id)
        except ValueError as exc:
            raise CrossTenantReferenceRefused(
                f"project identifier {project_id!r} is not a UUID",
                remedy="use a project identifier from this workspace's listing",
            ) from exc
        try:
            self._connection.execute(
                sa.text(
                    "INSERT INTO result_contracts "
                    "(tenant_id, id, project_id, contract_hash, approved) "
                    "VALUES (:tenant_id, :id, :project_id, :contract_hash, false)"
                ),
                {
                    "tenant_id": self._tenant_uuid,
                    "id": uuid.UUID(contract_id),
                    "project_id": project_uuid,
                    "contract_hash": contract_hash,
                },
            )
        except sa.exc.IntegrityError as exc:
            # RX-49: the composite foreign key is what refuses a reference to
            # another tenant's project, and referential checks bypass RLS, so
            # this is the layer that actually stops the relationship existing.
            raise CrossTenantReferenceRefused(
                f"project {project_id!r} is not in the authorised workspace, so a "
                "contract cannot reference it",
                remedy="create the contract under a project of this workspace",
            ) from exc
        return ContractRecord(
            tenant_id=self._tenant_id,
            id=contract_id,
            project_id=project_id,
            contract_hash=contract_hash,
            approved=False,
        )

    def get_contract(self, contract_id: str) -> ContractRecord | None:
        try:
            wanted = uuid.UUID(contract_id)
        except ValueError:
            return None
        row = self._connection.execute(
            sa.text(
                "SELECT tenant_id, id, project_id, contract_hash, approved "
                "FROM result_contracts WHERE id = :id"
            ),
            {"id": wanted},
        ).first()
        if row is None:
            return None
        return ContractRecord(
            tenant_id=str(row[0]),
            id=str(row[1]),
            project_id=str(row[2]),
            contract_hash=row[3],
            approved=bool(row[4]),
        )

    def list_contracts(self, project_id: str | None = None) -> tuple[ContractRecord, ...]:
        if project_id is None:
            rows = self._connection.execute(
                sa.text(
                    "SELECT tenant_id, id, project_id, contract_hash, approved "
                    "FROM result_contracts ORDER BY id"
                )
            ).all()
        else:
            try:
                wanted = uuid.UUID(project_id)
            except ValueError:
                return ()
            rows = self._connection.execute(
                sa.text(
                    "SELECT tenant_id, id, project_id, contract_hash, approved "
                    "FROM result_contracts WHERE project_id = :project_id ORDER BY id"
                ),
                {"project_id": wanted},
            ).all()
        return tuple(
            ContractRecord(
                tenant_id=str(r[0]),
                id=str(r[1]),
                project_id=str(r[2]),
                contract_hash=r[3],
                approved=bool(r[4]),
            )
            for r in rows
        )

    def mark_contract_approved(self, contract_id: str) -> ContractRecord:
        try:
            wanted = uuid.UUID(contract_id)
        except ValueError as exc:
            raise _missing_contract(contract_id) from exc
        row = self._connection.execute(
            sa.text(
                "UPDATE result_contracts SET approved = true WHERE id = :id "
                "RETURNING tenant_id, id, project_id, contract_hash, approved"
            ),
            {"id": wanted},
        ).first()
        if row is None:
            raise _missing_contract(contract_id)
        return ContractRecord(
            tenant_id=str(row[0]),
            id=str(row[1]),
            project_id=str(row[2]),
            contract_hash=row[3],
            approved=bool(row[4]),
        )


class SqlRepository:
    """PostgreSQL-backed repository (RX-47, RX-48, RX-49)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> sa.Engine:
        return self._engine

    @contextlib.contextmanager
    def unit_of_work(self, tenant_id: str) -> Iterator[TenantUnitOfWork]:
        with tenant_transaction(self._engine, tenant_id) as connection:
            yield _SqlUnitOfWork(normalise_tenant_id(tenant_id), connection)
