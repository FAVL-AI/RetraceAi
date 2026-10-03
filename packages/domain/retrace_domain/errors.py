"""Named refusals raised by the RETRACE domain layer.

Every refusal in this package is a *named* type carrying machine-readable
fields, because the properties this layer defends are security and scientific
properties: a caller must be able to tell "the store is corrupt" from "that
path escapes the root" from "no credential is configured", and a test must be
able to assert *which* rule fired rather than that something went wrong.

All of them derive from
:class:`retrace_contracts.exceptions.RetraceContractError`, so a caller that
already catches the contract layer's refusals also catches these. The two
exceptions reused unchanged from the contracts layer are
:class:`~retrace_contracts.exceptions.SnapshotIntegrityError` (RX-02) and
:class:`~retrace_contracts.exceptions.ContractNotApproved` (RX-04): this
package raises them rather than defining parallel types.

Requirement coverage:

* :class:`UnsafeSourcePath` -- RX-01 (an imported tree is untrusted input; a
  path that can escape the snapshot root is refused at walk time).
* :class:`LedgerIntegrityError` -- RX-04, RX-52 (a hash-chained append-only
  ledger whose middle has been edited or removed is detected, not trusted).
* :class:`LedgerAppendRefused` -- RX-52 (an append that would corrupt the
  record's meaning is refused rather than written).
* :class:`WriteRefused` -- RX-07 (the repair worker's write guard; a subclass
  of :class:`~retrace_contracts.exceptions.VerifierAuthorityError` so that the
  authority refusal keeps its contract-layer type while naming the rule).
* :class:`ProviderNotConfigured` -- RX-06, RX-40 and PRECHECK B6 (an
  unavailable provider reports its absence; it never simulates a response).
"""

from __future__ import annotations

from enum import Enum

from retrace_contracts import RetraceContractError, VerifierAuthorityError

__all__ = [
    "AuthorityRule",
    "LedgerAppendRefused",
    "LedgerIntegrityError",
    "PathRefusalRule",
    "ProviderNotConfigured",
    "RetraceDomainError",
    "UnsafeSourcePath",
    "WriteRefused",
]


class RetraceDomainError(RetraceContractError):
    """Base class for every refusal raised by :mod:`retrace_domain`."""


class PathRefusalRule(str, Enum):
    """Why a path in an untrusted source tree or manifest was refused (RX-01).

    Each member names one concrete rule so that a test can assert the rule and
    not merely the exception type. ``SYMLINK_DIRECTORY`` is refused outright
    rather than skipped: following it risks cycles and duplicated content,
    while silently *not* following it would omit data from a snapshot that
    claims to be complete.
    """

    ABSOLUTE_PATH = "ABSOLUTE_PATH"
    TRAVERSAL = "TRAVERSAL"
    UNSAFE_RELATIVE_PATH = "UNSAFE_RELATIVE_PATH"
    SYMLINK_ESCAPE = "SYMLINK_ESCAPE"
    SYMLINK_BROKEN = "SYMLINK_BROKEN"
    SYMLINK_DIRECTORY = "SYMLINK_DIRECTORY"
    NON_REGULAR_FILE = "NON_REGULAR_FILE"
    DESTINATION_ESCAPE = "DESTINATION_ESCAPE"
    DESTINATION_OCCUPIED = "DESTINATION_OCCUPIED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class AuthorityRule(str, Enum):
    """Why :class:`retrace_domain.authority.RepairAuthority` refused a write (RX-07).

    The rule is part of the refusal's payload because "the repair worker may
    not write here" is only useful to a reviewer if it says *which* boundary
    was crossed.
    """

    NO_SCRATCH_GRANTED = "NO_SCRATCH_GRANTED"
    PROTECTED_PREFIX = "PROTECTED_PREFIX"
    REFERENCE_OUTPUT_DIRECTORY = "REFERENCE_OUTPUT_DIRECTORY"
    APPROVAL_LEDGER = "APPROVAL_LEDGER"
    OUTSIDE_GRANTED_SCRATCH = "OUTSIDE_GRANTED_SCRATCH"
    UNSAFE_PATH = "UNSAFE_PATH"
    UNGUARDED_WRITE = "UNGUARDED_WRITE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class UnsafeSourcePath(RetraceDomainError):
    """A path in an untrusted tree or manifest cannot be admitted (RX-01).

    Attributes
    ----------
    rule:
        The :class:`PathRefusalRule` that refused the path.
    path:
        The offending path as it was encountered.
    root:
        The root the path was required to stay inside, when applicable.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        rule: PathRefusalRule,
        path: str,
        root: str | None = None,
    ) -> None:
        self.rule = rule
        self.path = path
        self.root = root
        if message is None:
            message = f"path refused by rule {rule.value}: {path}" + (
                f" (root={root})" if root else ""
            )
        super().__init__(message)


class LedgerIntegrityError(RetraceDomainError):
    """The approval ledger's hash chain does not verify (RX-04, RX-52).

    Attributes
    ----------
    rule:
        Short machine-readable name of the broken invariant, one of
        ``MALFORMED_LINE``, ``ENTRY_DIGEST_MISMATCH``, ``CHAIN_BREAK`` or
        ``SEQUENCE_BREAK``.
    line_number:
        1-based line number of the offending ledger line.
    expected / observed:
        The two values that disagreed, when the rule compares values.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        rule: str,
        line_number: int,
        expected: str | None = None,
        observed: str | None = None,
    ) -> None:
        self.rule = rule
        self.line_number = line_number
        self.expected = expected
        self.observed = observed
        if message is None:
            message = f"approval ledger integrity failure {rule} at line {line_number}"
            if expected or observed:
                message += f": expected={expected} observed={observed}"
        super().__init__(message)


class LedgerAppendRefused(RetraceDomainError):
    """An append to the approval ledger was refused (RX-52).

    Attributes
    ----------
    rule:
        Machine-readable reason, e.g. ``UNKNOWN_ENTRY``,
        ``ALREADY_SUPERSEDED``, ``DUPLICATE_ENTRY_ID`` or
        ``APPROVAL_CONTRACT_MISMATCH``.
    entry_id:
        The entry the append referred to, when known.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        rule: str,
        entry_id: str | None = None,
    ) -> None:
        self.rule = rule
        self.entry_id = entry_id
        if message is None:
            message = f"ledger append refused by rule {rule}" + (
                f" for entry_id={entry_id}" if entry_id else ""
            )
        super().__init__(message)


class WriteRefused(VerifierAuthorityError):
    """The repair worker attempted a write outside its authority (RX-07).

    Deliberately a subclass of
    :class:`~retrace_contracts.exceptions.VerifierAuthorityError` so that code
    and tests written against the contract layer's authority refusal keep
    working, while reviewers and tests gain :attr:`rule`.

    Attributes
    ----------
    rule:
        The :class:`AuthorityRule` that refused the write.
    protected_prefix:
        The protected prefix that matched, when :attr:`rule` is
        ``PROTECTED_PREFIX``.
    resolved_target:
        The target after symlink and ``..`` resolution -- the value the
        decision was actually made on, which is frequently not the value the
        caller passed.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        rule: AuthorityRule,
        target: str,
        actor: str,
        resolved_target: str | None = None,
        protected_prefix: str | None = None,
    ) -> None:
        self.rule = rule
        self.protected_prefix = protected_prefix
        self.resolved_target = resolved_target
        if message is None:
            message = (
                f"write refused by rule {rule.value}: actor={actor} target={target}"
                + (f" resolved={resolved_target}" if resolved_target else "")
                + (f" protected_prefix={protected_prefix}" if protected_prefix else "")
            )
        super().__init__(message, actor=actor, action="write", target=target)


class ProviderNotConfigured(RetraceDomainError):
    """A repair provider cannot run because its configuration is absent (RX-06, RX-40).

    Raised instead of returning a fabricated proposal. PRECHECK B6 records that
    no model-provider credential exists on this host, so the governed model
    route raises this on every call here; that is the honest behaviour, and it
    is asserted by a test rather than described in prose.

    Attributes
    ----------
    provider_id:
        Id of the provider that is unavailable.
    missing:
        The configuration field names that are absent, in declaration order.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        provider_id: str,
        missing: tuple[str, ...] = (),
    ) -> None:
        self.provider_id = provider_id
        self.missing = tuple(missing)
        if message is None:
            named = ", ".join(self.missing) if self.missing else "configuration"
            message = (
                f"provider {provider_id!r} is not configured; missing: {named}. "
                "No proposal is produced and no request is sent."
            )
        super().__init__(message)
