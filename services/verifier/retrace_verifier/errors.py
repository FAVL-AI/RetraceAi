"""Named refusals raised by the independent verifier (RX-09, RX-10, RX-15).

Every class here is a *refusal*, and the vocabulary is deliberately split so a
caller can never collapse three different situations into one "verification
failed":

* :class:`OutputParseRefused` -- RX-10. The payload was refused **before being
  deserialised**. This is the exception that proves a hostile artefact was not
  loaded; it is never raised after a successful parse.
* :class:`ReferenceUnavailable` -- RX-17. Required reference evidence is absent
  or unreadable. The verifier abstains on this; it never infers a pass.
* :class:`BundleRefused` -- RX-15, RX-16, RX-42. An evidence bundle broke a
  structural safety rule (zip-slip, size cap, ratio cap, member count).
* :class:`BundleIntegrityError` -- RX-02, RX-15. A recorded digest disagrees
  with the bytes. A bundle in this state is refused, never repaired: silently
  recomputing a digest to match tampered bytes would destroy the only property
  the bundle has.

:class:`~retrace_contracts.VerifierAuthorityError` is *not* redefined here. The
frozen contracts layer owns it, and a write attempted through a read-only
reference reader raises that exact class (RX-09).
"""

from __future__ import annotations

__all__ = [
    "BundleIntegrityError",
    "BundleRefused",
    "OutputParseRefused",
    "ReferenceUnavailable",
    "VerifierError",
]


class VerifierError(Exception):
    """Base class for every refusal raised by the verifier.

    Not derived from ``ValueError`` or ``OSError``: a broad ``except OSError``
    around a file read in calling code must not be able to swallow a refusal to
    parse or a refusal of authority.
    """


class OutputParseRefused(VerifierError):
    """A run output or reference payload was refused before deserialisation (RX-10).

    Attributes
    ----------
    reason:
        The specific rule that refused it -- extension, magic bytes, size,
        depth, key count, non-finite token, malformed structure.
    path:
        Where the payload came from, when known.
    detail:
        Human-readable detail naming the offending value.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str | None = None,
        path: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.reason = reason
        self.path = path
        self.detail = detail
        if message is None:
            message = "output payload refused without being deserialised"
            if reason:
                message += f": {reason}"
            if path:
                message += f" ({path})"
            if detail:
                message += f" -- {detail}"
        super().__init__(message)


class ReferenceUnavailable(VerifierError):
    """Required reference evidence is absent or unreadable (RX-17).

    Raised by a reference reader. The verifier turns it into a ``BLOCKED`` check
    and a ``BLOCKED_MISSING_EVIDENCE`` outcome rather than letting it propagate,
    because abstention is the scientifically correct response to absent evidence.
    """

    def __init__(
        self, message: str | None = None, *, path: str | None = None, reason: str | None = None
    ) -> None:
        self.path = path
        self.reason = reason
        if message is None:
            message = "reference evidence unavailable"
            if path:
                message += f": {path}"
            if reason:
                message += f" -- {reason}"
        super().__init__(message)


class BundleRefused(VerifierError):
    """An evidence bundle broke a structural safety rule (RX-15, RX-16, RX-42).

    Attributes
    ----------
    reason:
        Which rule refused it: ``zip-slip``, ``member-too-large``,
        ``bundle-too-large``, ``compression-ratio``, ``too-many-members``,
        ``absolute-member-path``, ``non-regular-member``, ``missing-member``.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str | None = None,
        member: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.reason = reason
        self.member = member
        self.detail = detail
        if message is None:
            message = "evidence bundle refused"
            if reason:
                message += f": {reason}"
            if member:
                message += f" (member {member!r})"
            if detail:
                message += f" -- {detail}"
        super().__init__(message)


class BundleIntegrityError(VerifierError):
    """A recorded digest in a bundle disagrees with the bytes (RX-02, RX-15).

    The bundle is refused. It is never repaired by recomputing the digest: the
    digest is the only thing that makes the bundle evidence, so replacing it to
    match altered bytes would turn tampering into a silent success.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        subject: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
    ) -> None:
        self.subject = subject
        self.expected = expected
        self.observed = observed
        if message is None:
            message = "evidence bundle integrity check failed"
            if subject:
                message += f" for {subject}"
            if expected or observed:
                message += f": recorded={expected} computed={observed}"
            message += "; the bundle is refused, not repaired"
        super().__init__(message)
