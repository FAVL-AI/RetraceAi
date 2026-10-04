"""The confined execution profile, and the identity half that stays open (RX-08, RX-09).

WHAT THIS FILE IS FOR.

``docs/security/THREAT_MODEL.md`` lists three things still open under T2. The
third is that ``DEFAULT_LIMITS.filesystem_confinement`` is ``NONE`` and no caller
in the repository requests confinement - "owed by ``services/api``" and "a
release blocker for any execution endpoint". These tests assert the caller now
exists, that its declaration names every authoritative artefact, and that the
measurement of the identity half says what is actually configured.

THE DECLARATION IS ASSERTED BY KIND, NOT BY COUNT.

A declaration that silently lost its approval-ledger entry would still be
non-empty, would still satisfy the policy validator, and would still produce a
confined-looking run. So every member of ``PROTECTED_PATH_KINDS`` is checked by
name, and the enumeration is compared against the realised declaration in both
directions.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
from typing import Any

import pytest
from api_support import TENANT_A, Harness, build_config
from pydantic import ValidationError
from retrace_api.web.errors import ExecutionProfileNotConfigured
from retrace_api.web.run_profile import (
    PROTECTED_PATH_KINDS,
    IdentitySeparation,
    declared_paths,
    execution_profile,
    identity_separation,
)
from retrace_api.web.workspace import StorageNotConfigured
from retrace_runner import DEFAULT_LIMITS, ExecutionLimits, FilesystemConfinement, NetworkIsolation

# --------------------------------------------------------------------------- #
# The declaration.
# --------------------------------------------------------------------------- #


def test_the_profile_requests_kernel_mount_namespace_confinement(harness: Harness) -> None:
    """RX-08: the caller the threat model says is owed by services/api."""
    profile = execution_profile(harness.state.config, tenant_id=TENANT_A)
    assert profile.limits.filesystem_confinement is FilesystemConfinement.KERNEL_MOUNT_NAMESPACE
    assert profile.limits.network is NetworkIsolation.KERNEL_NAMESPACE


def test_the_shipped_default_is_still_unconfined(harness: Harness) -> None:
    """The contrast that makes the profile meaningful.

    ``DEFAULT_LIMITS`` cannot know what to protect, so it is ``NONE``. Asserting
    it here records that the profile is a DECISION taken by this service rather
    than a default it inherited - and if the runner's default were ever changed
    to something confined-looking, this would fail and the change would be
    noticed from the API side too.
    """
    assert DEFAULT_LIMITS.filesystem_confinement is FilesystemConfinement.NONE
    assert DEFAULT_LIMITS.protected_paths == ()
    profile = execution_profile(harness.state.config, tenant_id=TENANT_A)
    assert profile.limits.policy_digest != DEFAULT_LIMITS.policy_digest


@pytest.mark.parametrize("kind", PROTECTED_PATH_KINDS)
def test_every_authoritative_artefact_kind_is_declared(harness: Harness, kind: str) -> None:
    """RX-08: declared-deny means the declaration IS the control."""
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    assert kind in declaration.by_kind, f"{kind} is not in the declaration"
    path = declaration.by_kind[kind]
    assert path in declaration.protected
    assert path.startswith("/"), f"{kind} declared a relative path: {path}"
    assert path == os.path.normpath(path), f"{kind} declared an unnormalised path: {path}"


def test_the_declaration_enumeration_matches_the_realised_declaration(
    harness: Harness,
) -> None:
    """Both directions: a path with no kind, and a kind with no path, both fail."""
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    assert set(declaration.by_kind) == set(PROTECTED_PATH_KINDS)
    assert len(declaration.protected) == len(PROTECTED_PATH_KINDS)


def test_the_declared_paths_are_the_ones_the_service_actually_writes(
    harness: Harness,
) -> None:
    """A profile protecting a SIMILAR directory protects nothing.

    The ledger, the content store, the index and the evidence area are compared
    against the paths ``TenantWorkspace`` itself resolves, so the declaration
    cannot drift away from the code that writes them.
    """
    workspace = harness.state.workspaces.for_tenant(TENANT_A)
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    assert declaration.by_kind["approval-ledger"] == str(workspace.root / "approvals.jsonl")
    assert declaration.by_kind["reference-outputs"] == str(workspace.root / "objects")
    assert declaration.by_kind["object-index"] == str(workspace.root / "index")
    assert declaration.by_kind["evidence"] == str(workspace.root / "evidence")


def test_the_package_directories_are_the_installed_ones(harness: Harness) -> None:
    """Resolved from the imported modules, so a wheel install is also correct."""
    import retrace_contracts
    import retrace_verifier

    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    assert declaration.by_kind["contracts-package"] == str(
        pathlib.Path(retrace_contracts.__file__).resolve().parent
    )
    assert declaration.by_kind["verifier-package"] == str(
        pathlib.Path(retrace_verifier.__file__).resolve().parent
    )
    assert pathlib.Path(declaration.by_kind["contracts-package"]).is_dir()
    assert pathlib.Path(declaration.by_kind["verifier-package"]).is_dir()


def test_the_schema_directory_is_the_configured_one_and_holds_the_schemas(
    harness: Harness,
) -> None:
    """RX-08: specs/schemas is a deployment fact, and it is a real directory."""
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    schemas = pathlib.Path(declaration.by_kind["schemas"])
    assert schemas.is_dir()
    assert (schemas / "result_contract.schema.json").is_file()


def test_the_secret_path_is_declared_and_is_not_also_protected(harness: Harness) -> None:
    """Read-only and replaced-by-tmpfs cannot both hold for one path."""
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    assert declaration.secret == (str(harness.secret_root.resolve()),)
    assert set(declaration.secret).isdisjoint(declaration.protected)


def test_a_tenant_declaration_names_that_tenants_own_paths(harness: Harness) -> None:
    """Two tenants get two declarations, and neither names the other's area."""
    from api_support import TENANT_B

    a = declared_paths(harness.state.config, tenant_id=TENANT_A)
    b = declared_paths(harness.state.config, tenant_id=TENANT_B)
    assert a.by_kind["approval-ledger"] != b.by_kind["approval-ledger"]
    assert TENANT_B not in a.by_kind["approval-ledger"]
    assert TENANT_A not in b.by_kind["approval-ledger"]


def test_the_policy_digest_covers_the_declaration(harness: Harness) -> None:
    """RX-15: a run under one declaration cannot be confused with another."""
    profile = execution_profile(harness.state.config, tenant_id=TENANT_A)
    # `ExecutionLimits` is a pydantic record, not a dataclass: `model_copy`,
    # which revalidates nothing, would not exercise the validator either - so
    # the narrowed policy is constructed rather than copied.
    narrowed = ExecutionLimits(
        network=profile.limits.network,
        filesystem_confinement=profile.limits.filesystem_confinement,
        protected_paths=profile.limits.protected_paths[:-1],
        secret_paths=profile.limits.secret_paths,
    )
    assert narrowed.policy_digest != profile.limits.policy_digest
    identical = ExecutionLimits(
        network=profile.limits.network,
        filesystem_confinement=profile.limits.filesystem_confinement,
        protected_paths=profile.limits.protected_paths,
        secret_paths=profile.limits.secret_paths,
    )
    assert identical.policy_digest == profile.limits.policy_digest


# --------------------------------------------------------------------------- #
# The validator refuses a declaration that does not mean what it looks like.
# --------------------------------------------------------------------------- #


def test_confinement_with_no_declared_paths_is_refused() -> None:
    """NEGATIVE CONTROL: this is why the declaration has to be reviewed.

    The runner's own validator refuses the mode with an empty declaration, so
    the exposed default cannot simply be flipped - a service profile has to say
    what is authoritative. That refusal is what makes the enumeration above a
    control rather than documentation.
    """
    with pytest.raises(ValidationError) as refusal:
        ExecutionLimits(filesystem_confinement=FilesystemConfinement.KERNEL_MOUNT_NAMESPACE)
    assert "confine nothing" in str(refusal.value)


def test_declared_paths_with_no_confinement_are_refused() -> None:
    """NEGATIVE CONTROL in the other direction: an unenforced protection list."""
    with pytest.raises(ValidationError) as refusal:
        ExecutionLimits(
            filesystem_confinement=FilesystemConfinement.NONE,
            protected_paths=("/srv/retrace/approvals.jsonl",),
        )
    assert "nothing would enforce them" in str(refusal.value)


def test_a_relative_declared_path_is_refused() -> None:
    """A relative path would resolve against the child's cwd."""
    with pytest.raises(ValidationError):
        ExecutionLimits(
            filesystem_confinement=FilesystemConfinement.KERNEL_MOUNT_NAMESPACE,
            protected_paths=("srv/retrace/approvals.jsonl",),
        )


def test_the_real_profile_satisfies_the_validator(harness: Harness) -> None:
    """POSITIVE CONTROL for the three refusals above."""
    profile = execution_profile(harness.state.config, tenant_id=TENANT_A)
    assert profile.limits.protected_paths
    assert profile.limits.secret_paths


# --------------------------------------------------------------------------- #
# An incompletely configured deployment reports NEEDS_CONFIGURATION.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("absent", "setting"),
    [("schema_root", "RETRACE_SCHEMA_ROOT"), ("secret_root", "RETRACE_SECRET_ROOT")],
)
def test_an_absent_declaration_setting_is_reported_not_guessed(
    harness: Harness, absent: str, setting: str
) -> None:
    """RX-08: a guessed path would be a declaration nobody reviewed."""
    config = dataclasses.replace(harness.state.config, **{absent: None})
    with pytest.raises(ExecutionProfileNotConfigured) as refusal:
        declared_paths(config, tenant_id=TENANT_A)
    assert setting in refusal.value.extra["missing"]
    assert refusal.value.extra["status"] == "NEEDS_CONFIGURATION"
    assert refusal.value.extra["reference"]


def test_an_unconfigured_storage_root_is_reported_as_storage_not_configured(
    harness: Harness,
) -> None:
    """A different refusal, because it is a different missing thing."""
    config = dataclasses.replace(harness.state.config, storage_root=None)
    with pytest.raises(StorageNotConfigured):
        declared_paths(config, tenant_id=TENANT_A)


# --------------------------------------------------------------------------- #
# The identity half, measured.
# --------------------------------------------------------------------------- #


def test_the_identity_half_is_open_in_this_build(harness: Harness) -> None:
    """RX-09, T2 part 3: measured from configuration, not asserted."""
    separation = identity_separation(harness.state.config)
    assert separation.satisfied is False
    assert separation.distinct_os_identity is False
    assert separation.distinct_database_identities is False
    reasons = " ".join(separation.unmet())
    assert "RETRACE_RUNNER_OS_USER" in reasons
    assert "RETRACE_RUNNER_DATABASE_URL" in reasons
    assert "RETRACE_VERIFIER_DATABASE_URL" in reasons


def test_the_measurement_reports_the_account_this_process_actually_runs_as(
    harness: Harness,
) -> None:
    """Read from the password database, not from ``$USER``.

    An environment variable is request-adjacent configuration: a deployment that
    exported ``USER=retrace-runner`` would otherwise appear to have a separation
    it does not have.
    """
    separation = identity_separation(harness.state.config)
    import pwd

    assert separation.process_os_user == pwd.getpwuid(os.geteuid()).pw_name


def test_a_runner_account_equal_to_this_one_is_not_a_separation(harness: Harness) -> None:
    """NEGATIVE CONTROL: the check is not merely "the setting is non-empty"."""
    current = identity_separation(harness.state.config).process_os_user
    config = dataclasses.replace(
        harness.state.config,
        runner_os_user=current,
        runner_database_url="postgresql://runner@localhost/retrace",
        verifier_database_url="postgresql://verifier@localhost/retrace",
    )
    separation = identity_separation(config)
    assert separation.distinct_database_identities is True
    assert separation.distinct_os_identity is False
    assert separation.satisfied is False
    assert any("already runs as" in reason for reason in separation.unmet())


def test_shared_database_credentials_are_not_a_separation() -> None:
    """RX-09: the runner and the verifier must not share a credential."""
    shared = IdentitySeparation(
        api_database_url="postgresql://api@localhost/retrace",
        runner_database_url="postgresql://same@localhost/retrace",
        verifier_database_url="postgresql://same@localhost/retrace",
        runner_os_user="retrace-runner",
        process_os_user="retrace-api",
    )
    assert shared.distinct_os_identity is True
    assert shared.distinct_database_identities is False
    assert shared.satisfied is False
    assert any("not all distinct" in reason for reason in shared.unmet())


def test_a_fully_configured_separation_is_reported_as_satisfied() -> None:
    """POSITIVE CONTROL: the measurement is not hardwired to refuse."""
    configured = IdentitySeparation(
        api_database_url="postgresql://api@localhost/retrace",
        runner_database_url="postgresql://runner@localhost/retrace",
        verifier_database_url="postgresql://verifier@localhost/retrace",
        runner_os_user="retrace-runner",
        process_os_user="retrace-api",
    )
    assert configured.satisfied is True
    assert configured.unmet() == ()


def test_the_measurement_states_what_it_does_not_establish() -> None:
    """A satisfied measurement must not read as a proven separation.

    Nothing here probes whether the OS account can be assumed or whether the
    database roles are genuinely restricted. The caveat travels with the
    measurement into the refusal body, so a reader of the response sees it too.
    """
    separation = IdentitySeparation(
        api_database_url=None,
        runner_database_url=None,
        verifier_database_url=None,
        runner_os_user=None,
        process_os_user="retrace-api",
    )
    assert "CONFIGURATION checks" in separation.caveat
    assert "achievability probe is owed" in separation.caveat


# --------------------------------------------------------------------------- #
# The profile does not become a permission.
# --------------------------------------------------------------------------- #


def test_the_profile_exposes_no_property_a_handler_could_treat_as_permission(
    make_harness: Any,
) -> None:
    """The profile measures; it does not authorise.

    With both halves of T2 configured as closed, the profile reports that - and
    the run route still refuses, because no route invokes the runner. The
    property is therefore not named ``admissible``, and
    ``test_run_gate.py::test_the_gate_still_refuses_when_the_identity_half_is_
    configured`` asserts the route's behaviour.
    """
    current = identity_separation(build_config(pathlib.Path("/"), pathlib.Path("/")))
    harness = make_harness(
        runner_os_user=f"{current.process_os_user}-runner",
        runner_database_url="postgresql://runner@localhost/retrace",
        verifier_database_url="postgresql://verifier@localhost/retrace",
    )
    profile = execution_profile(harness.state.config, tenant_id=TENANT_A)
    assert profile.confinement_and_identity_met is True
    assert not hasattr(profile, "admissible")


def test_absent_declared_paths_are_reported_rather_than_ignored(harness: Harness) -> None:
    """A declared path that does not exist is a run that would be REFUSED.

    The approval ledger is legitimately absent until a workspace's first
    approval, so this is a diagnostic rather than a construction error - but it
    is a REPORTED one, because the mount binds declared paths and a silently
    missing bind is the difference between confined and not.
    """
    declaration = declared_paths(harness.state.config, tenant_id=TENANT_A)
    absent = declaration.absent()
    assert any(entry.startswith("approval-ledger=") for entry in absent)
    assert not any(entry.startswith("contracts-package=") for entry in absent)
