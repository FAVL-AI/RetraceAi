"""The execution gate, and the policy digest an approval binds (RX-05, RX-08).

WHY THERE IS A POLICY DOCUMENT AT ALL WHEN NOTHING CAN EXECUTE.

An approval binds an environment policy digest (RX-05). If that digest were a
placeholder, an approval granted today would remain valid once real execution
landed under a *different* policy - which is exactly the invalidation the
binding exists to cause. So the policy is a real document describing the
confinement execution WOULD require, its digest is canonical, and the digest is
what the ledger records. The day confinement lands, the policy document changes,
the digest changes, and every approval granted under the gated policy is
invalidated rather than silently inherited.

WHY THE GATE IS NOT A FEATURE FLAG.

A flag invites being switched on. :func:`execution_refusal` reports the measured
state of T2 and names the artefacts that would have to change for execution to
be admissible: the confinement in ``services/runner`` entered for the child, a
restricted database role for the runner, and the inversion of the GAP tests in
``tests/authority`` which currently assert today's permissive behaviour on
purpose. None of those is a configuration value.
"""

from __future__ import annotations

from typing import Any, Final

from retrace_api.web.errors import ExecutionBlocked
from retrace_contracts import canonical_digest

__all__ = [
    "ENVIRONMENT_POLICY_DIGEST",
    "EXECUTION_GATE_PRECONDITIONS",
    "execution_policy_document",
    "execution_refusal",
]

#: What must be true before any execution endpoint may return anything but a
#: refusal. Each entry is a repository artefact, not a setting.
EXECUTION_GATE_PRECONDITIONS: Final[tuple[str, ...]] = (
    "the runner enters a mount namespace with protected paths bind-mounted "
    "read-only and credential directories replaced by an empty tmpfs",
    "the runner connects as a restricted database role that is neither owner, "
    "superuser nor BYPASSRLS",
    "the GAP tests in tests/authority/test_t2_enforcement.py are inverted, "
    "because they currently assert the permissive behaviour on purpose",
)


def execution_policy_document() -> dict[str, Any]:
    """The environment and action policy an approval is bound to (RX-05).

    Canonical and stable: no clock, no host detail, no random value. Two
    approvals granted under the same policy therefore bind the same digest, and
    a change to the policy changes every subsequent binding.
    """
    return {
        "policy_version": 1,
        "execution_admitted": False,
        "gate": "T2",
        "network": "DENY_ALL",
        "write_confinement": "SCRATCH_ONLY",
        "filesystem_confinement": "MOUNT_NAMESPACE_REQUIRED",
        "database_identity": "RESTRICTED_ROLE_REQUIRED",
        "preconditions": list(EXECUTION_GATE_PRECONDITIONS),
    }


#: The digest recorded in every approval this build grants.
ENVIRONMENT_POLICY_DIGEST: Final[str] = canonical_digest(
    execution_policy_document(), type_tag="retrace.ExecutionPolicy"
)


def execution_refusal(*, contract_id: str, snapshot_id: str) -> ExecutionBlocked:
    """The documented blocked state for an execution request (RX-08).

    Carries the identifiers so the refusal is auditable against the request that
    caused it, and the policy digest so a reader can see which policy was in
    force when execution was refused.
    """
    return ExecutionBlocked(
        "execution is refused: threat T2 is measured and OPEN. A child process can "
        "currently write the approval ledger, a reference output, verifier code or a "
        "verification verdict, and nothing denies it, so an execution result produced "
        "here could not be distinguished from a manufactured one",
        remedy="execution stays refused until the runner is confined and holds a "
        "restricted database identity; no configuration value opens this gate",
        extra={
            "contract_id": contract_id,
            "snapshot_id": snapshot_id,
            "environment_policy_digest": ENVIRONMENT_POLICY_DIGEST,
            "preconditions": list(EXECUTION_GATE_PRECONDITIONS),
        },
    )
