"""Named refusals raised by the isolated runner (RX-08).

Every one of these is a *refusal to execute*, not a degraded execution. The
runner has exactly one failure posture: if a requested isolation capability
cannot be established, the run does not happen (RX-08). There is deliberately
no exception in this module that means "ran it anyway, unsandboxed".

Requirement coverage:

* :class:`ExecutionEnvironmentUnavailable` -- RX-08. A notebook kernel, or the
  notebook machinery itself, is not available on this host. Raised *instead of*
  producing an :class:`~retrace_runner.results.ExecutionResult`, so a caller can
  never mistake an unavailable environment for a run that failed its science.
* :class:`IsolationUnavailable` -- RX-08. A requested isolation capability
  (process-group containment, address-space cap, kernel network namespace,
  scratch confinement) could not be established. Fail closed.
* :class:`FilesystemConfinementUnavailable` -- RX-08. The *kernel filesystem*
  confinement specifically could not be established, named separately because it
  is the half of T2 a verdict may cite. A subclass of
  :class:`IsolationUnavailable`, so existing fail-closed handling still catches
  it and no caller can accidentally proceed.
* :class:`ScratchConfinementError` -- RX-08. The scratch root could not be
  created, is not a directory, or the notebook path cannot be admitted into it.
* :class:`NotebookAdmissionRefused` -- RX-08, RX-42. The thing offered for
  execution is not an admissible notebook artefact (wrong suffix, symlink,
  unparseable, or outside the authorised source root). The runner takes a
  *path to a declared notebook*; it has no entrypoint that accepts source code.
"""

from __future__ import annotations

__all__ = [
    "ExecutionEnvironmentUnavailable",
    "FilesystemConfinementUnavailable",
    "IsolationUnavailable",
    "NotebookAdmissionRefused",
    "RunnerError",
    "ScratchConfinementError",
]


class RunnerError(Exception):
    """Base class for every refusal raised by the runner (RX-08).

    Not a subclass of ``ValueError`` or ``OSError``: a broad ``except OSError``
    around a filesystem call in calling code must not be able to swallow a
    refusal to isolate.
    """


class ExecutionEnvironmentUnavailable(RunnerError):
    """No usable notebook execution environment on this host (RX-08).

    Raised before any subprocess is started, so this exception is positive
    evidence that *nothing executed*. The runner never substitutes a simulated
    run for a missing kernel.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        component: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.component = component
        self.detail = detail
        if message is None:
            message = "notebook execution environment unavailable; nothing was executed"
            if component:
                message += f": {component}"
            if detail:
                message += f" -- {detail}"
        super().__init__(message)


class IsolationUnavailable(RunnerError):
    """A requested isolation capability could not be established (RX-08).

    The run is refused. There is no fallback to unsandboxed host execution:
    an isolation request that cannot be honoured is a reason not to run, never
    a reason to run with less isolation than was asked for.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        capability: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.capability = capability
        self.detail = detail
        if message is None:
            message = "requested isolation capability unavailable; run refused"
            if capability:
                message += f": {capability}"
            if detail:
                message += f" -- {detail}"
        super().__init__(message)


class FilesystemConfinementUnavailable(IsolationUnavailable):
    """The requested kernel filesystem confinement could not be established (RX-08).

    Raised by the parent before anything is executed, or derived from the child's
    refusal, for every failure mode alike: the namespace is unavailable on this
    host, a declared path does not exist, a bind did not take effect, a writable
    submount survives under a protected path, or the run's own scratch area lies
    inside a path declared protected.

    There is no variant of this exception that means "ran with less confinement".
    """

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        super().__init__(message, capability="kernel filesystem confinement", detail=detail)


class ScratchConfinementError(RunnerError):
    """The scratch write root could not be established (RX-08)."""

    def __init__(self, message: str | None = None, *, path: str | None = None) -> None:
        self.path = path
        if message is None:
            message = "scratch confinement could not be established"
            if path:
                message += f" at {path}"
        super().__init__(message)


class NotebookAdmissionRefused(RunnerError):
    """The offered artefact is not an admissible notebook (RX-08, RX-42).

    ``reason`` names the specific admission rule that refused it so the refusal
    is reviewable rather than merely negative.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str | None = None,
        path: str | None = None,
    ) -> None:
        self.reason = reason
        self.path = path
        if message is None:
            message = "notebook admission refused"
            if reason:
                message += f": {reason}"
            if path:
                message += f" ({path})"
        super().__init__(message)
