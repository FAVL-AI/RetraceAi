"""The execution gate, and the policy digest an approval binds (RX-05, RX-08, RX-09).

WHY THERE IS A POLICY DOCUMENT AT ALL WHEN NOTHING CAN EXECUTE.

An approval binds an environment policy digest (RX-05). If that digest were a
placeholder, an approval granted today would remain valid once real execution
landed under a *different* policy - which is exactly the invalidation the
binding exists to cause. So the policy is a real document describing the
confinement execution requires, its digest is canonical, and the digest is what
the ledger records. The day the identity half closes, the document changes, the
digest changes, and every approval granted under the gated policy is invalidated
rather than silently inherited.

The document is deliberately TENANT-INDEPENDENT. The per-tenant confinement
declaration lives in :mod:`retrace_api.web.run_profile` and carries its own
``policy_digest``; binding an approval to that one would make an approval
invalid the moment a storage root moved, which is a deployment change rather
than a change to the scientific envelope. Both digests are reported in the
refusal, so neither is hidden.

WHY THE GATE IS NOT A FEATURE FLAG.

A flag invites being switched on. :func:`execution_refusal` reports a MEASURED
state: :class:`~retrace_api.web.run_profile.IdentitySeparation` asks what is
configured, and the refusal quotes the specific requirements that are unmet. The
filesystem half of T2 is closed and the profile requests it; what remains open is
the identity half, and no configuration value in this module opens it.
"""

from __future__ import annotations

from typing import Any, Final

from retrace_api.web.errors import T2_REFERENCE, ExecutionBlocked
from retrace_api.web.run_profile import ExecutionProfile
from retrace_contracts import canonical_digest

__all__ = [
    "ENVIRONMENT_POLICY_DIGEST",
    "EXECUTION_GATE_PRECONDITIONS",
    "EXECUTION_NOT_IMPLEMENTED",
    "execution_policy_document",
    "execution_refusal",
]

#: The reason that remains unmet no matter how the deployment is configured.
#:
#: Stated as its own entry because it is the one a reader is most likely to
#: assume away. Closing T2's identity half would make a confined run
#: *admissible*; it would not make one *possible*, because no route in this
#: service invokes the runner. A gate that opened on configuration alone would
#: hand back a success-shaped response for work nothing performed, which is the
#: fabrication the gate exists to prevent.
EXECUTION_NOT_IMPLEMENTED: Final = (
    "no execution implementation is wired into services/api: no route invokes the "
    "runner, so there is nothing for an opened gate to run (OPEN)"
)

#: What must be true before any execution endpoint may return anything but a
#: refusal. Each entry is a repository artefact or a deployment identity, not a
#: setting that changes behaviour on its own.
#:
#: The first entry used to say the runner must enter a mount namespace. It does:
#: ``FilesystemConfinement.KERNEL_MOUNT_NAMESPACE`` exists, is verified back from
#: ``/proc/self/mountinfo`` inside the child, and refuses a downgrade. What was
#: actually owed was a CALLER that requests it with a reviewed declaration, and
#: that is what :mod:`retrace_api.web.run_profile` now is - so the precondition
#: is restated as the thing that is still missing.
EXECUTION_GATE_PRECONDITIONS: Final[tuple[str, ...]] = (
    "the service profile requests FilesystemConfinement.KERNEL_MOUNT_NAMESPACE with a "
    "reviewed declaration of the protected and secret paths (DONE: "
    "retrace_api.web.run_profile)",
    "the runner's child executes under a distinct OS identity, so confinement is not "
    "merely a cooperative arrangement between one account and itself (OPEN)",
    "the runner and the verifier each connect as a restricted database role, distinct "
    "from each other and from the API, and neither is owner, superuser nor BYPASSRLS "
    "(OPEN, RX-09)",
    "the GAP tests in tests/authority/test_t2_enforcement.py are inverted, because they "
    "currently assert the permissive behaviour on purpose",
    EXECUTION_NOT_IMPLEMENTED,
)


def execution_policy_document() -> dict[str, Any]:
    """The environment and action policy an approval is bound to (RX-05).

    Canonical and stable: no clock, no host detail, no random value, no tenant.
    Two approvals granted under the same policy therefore bind the same digest,
    and a change to the policy changes every subsequent binding.
    """
    return {
        "policy_version": 2,
        "execution_admitted": False,
        "gate": "T2",
        "network": "DENY_ALL",
        "write_confinement": "SCRATCH_ONLY",
        "filesystem_confinement": "KERNEL_MOUNT_NAMESPACE",
        # The two halves of T2, named separately: a reader of an approval can
        # see which one was open when the approval was granted.
        "filesystem_half": "CLOSED_OVER_DECLARED_PATHS",
        "identity_half": "OPEN",
        "database_identity": "RESTRICTED_ROLE_REQUIRED",
        "preconditions": list(EXECUTION_GATE_PRECONDITIONS),
    }


#: The digest recorded in every approval this build grants.
ENVIRONMENT_POLICY_DIGEST: Final[str] = canonical_digest(
    execution_policy_document(), type_tag="retrace.ExecutionPolicy"
)


def execution_refusal(
    *, contract_id: str, snapshot_id: str, profile: ExecutionProfile
) -> ExecutionBlocked:
    """The documented blocked state for an execution request (RX-08, RX-09).

    Carries the identifiers so the refusal is auditable against the request that
    caused it, the environment policy digest the approval binds, and the
    CONFINED profile the run would have used. The last of those is what makes
    the gate a one-line change rather than an invitation to invent a profile
    later: the protected paths a future verdict would cover are visible today.
    """
    unmet = (*profile.separation.unmet(), EXECUTION_NOT_IMPLEMENTED)
    return ExecutionBlocked(
        "execution is refused: threat T2's IDENTITY half is open. The filesystem half is "
        "closed - the profile below requests KERNEL_MOUNT_NAMESPACE over a reviewed "
        "declaration - but no distinct OS execution identity is established and the "
        "runner and verifier hold no distinct restricted database credentials. A child "
        "confined by its own parent, under the parent's uid and with the parent's "
        "database identity, cannot produce a result distinguishable from a manufactured "
        "one. Separately, and unconditionally: no route here invokes the runner, so "
        f"there is nothing an opened gate would run. See {T2_REFERENCE}",
        remedy="give the runner a distinct OS account and the runner and verifier "
        "distinct restricted database roles, then wire an execution path; no "
        "configuration value in the API opens this gate on its own",
        extra={
            "contract_id": contract_id,
            "snapshot_id": snapshot_id,
            "blocked_half": "IDENTITY",
            "filesystem_half": "CLOSED_OVER_DECLARED_PATHS",
            "environment_policy_digest": ENVIRONMENT_POLICY_DIGEST,
            "preconditions": list(EXECUTION_GATE_PRECONDITIONS),
            "unmet_preconditions": list(unmet),
            "identity_separation_caveat": profile.separation.caveat,
            "execution_profile": profile.summary(),
        },
    )
