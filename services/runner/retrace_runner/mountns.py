"""Kernel-enforced filesystem confinement via an unprivileged mount namespace (RX-08).

WHY THIS MODULE EXISTS
======================
:mod:`retrace_runner.guard` is an in-process path guard. It refuses the writes it
is *asked* about, and it cannot refuse a write that never asks: native code --
``ctypes``, a C extension, a compiled numerical library -- reaches ``open(2)``
without passing through any Python-level patch. That was not a theory. It was
measured: ``tests/authority/test_t2_enforcement.py`` recorded a child process
overwriting a stand-in approval ledger, a reference output, a verifier module and
a verification verdict, four for four ALLOWED, and reading a canary credential.

This module moves that one enforcement from the interpreter into the kernel. A
child that has entered a user+mount namespace bind-mounts every **declared**
protected path read-only and replaces every **declared** secret directory with an
empty ``tmpfs``. The kernel then applies the denial to every write path --
``open``, ``os.open``, ``unlink``, ``ctypes``, a subprocess -- because it does not
enumerate call sites.

WHAT THIS DOES NOT ACHIEVE -- read this before quoting it as a boundary
=======================================================================
* **No distinct OS execution identity.** On this workstation ``sudo`` requires a
  password and ``chown`` is refused, so credential separation by file ownership
  is impossible here. The confined child runs as the same uid as its parent.
  What is confined is therefore a **cooperatively launched child**: the parent
  chooses to hand it a namespace in which the protected paths are read-only.
* **Not protection against a compromised host.** A process that already holds
  the parent's privileges can decline to confine itself. This closes the path by
  which *executed scientific code* reaches the evidence used to judge it; it
  does not defend against an attacker who controls the launcher.
* **The infrastructure-administrator trust boundary is unchanged.** Anyone who
  can write the host filesystem directly, or change what the runner declares,
  is outside this mechanism entirely.
* **It confines what the caller declares, and nothing else.** This is a
  declared-deny confinement, not a read-only root with the scratch area carved
  out of it. A protected path the policy does not list stays writable, so an
  incomplete declaration is an incomplete control -- the declaration is part of
  the security property and belongs under review with the rest of the policy.
* **A separate filesystem mounted under a declared path** would keep its own
  write permission after a recursive bind, because ``MS_REMOUNT|MS_RDONLY``
  applies to one mount. :func:`unprotected_submounts` therefore *looks*, and
  :func:`apply_confinement` refuses the run rather than reporting a confinement
  it did not achieve.

Availability is probed, never assumed: :func:`probe_confinement_capability`
*attempts the real operation* in a throwaway child -- including a control write
that must still succeed -- because "``os.unshare`` exists" is not evidence that
``unshare`` is permitted by this kernel's policy.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import re
import subprocess  # noqa: S404 - the probe child IS the capability measurement
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Final

from .netns import NamespaceUnavailable

__all__ = [
    "FILESYSTEM_LIMITS",
    "MountConfinementUnavailable",
    "MountEntry",
    "RealisedConfinement",
    "apply_confinement",
    "confinement_support_reason",
    "interpret_probe",
    "parse_mountinfo",
    "probe_confinement_capability",
    "unprotected_submounts",
]

MS_BIND: Final[int] = 0x1000
MS_REC: Final[int] = 0x4000
MS_PRIVATE: Final[int] = 0x40000
MS_REMOUNT: Final[int] = 0x20
MS_RDONLY: Final[int] = 0x1

TMPFS_FSTYPE: Final[bytes] = b"tmpfs"
HIDDEN_TMPFS_OPTIONS: Final[bytes] = b"mode=000,size=4k"
"""An empty, unreadable, 4 KiB ``tmpfs``.

Read-only is the wrong tool for a secret: a credential the worker can read is a
credential it can use. Hiding replaces the directory's contents instead of
merely protecting them.
"""

EROFS: Final[int] = 30
PROBE_TIMEOUT_SECONDS: Final[float] = 60.0
_SECRET_DENIAL_ERRNOS: Final[frozenset[int]] = frozenset({2, 13})
"""``ENOENT`` or ``EACCES``.

Both are refusals to reach the credential. The property under test is
unreachability; which of the two the kernel reports for a ``mode=000`` ``tmpfs``
root is a kernel detail and pinning one of them would pin an implementation
rather than the property.
"""

FILESYSTEM_LIMITS: Final[tuple[str, ...]] = (
    "A mount namespace confines a cooperatively launched child. It is not "
    "protection against a compromised host, and it establishes no distinct OS "
    "execution identity: the child runs as the same uid as its parent.",
    "Only the paths the policy declares are confined. A protected path that is "
    "not declared stays writable, so the declaration is part of the control.",
    "The infrastructure-administrator trust boundary is unchanged.",
    "Availability depends on kernel policy for unprivileged user namespaces "
    "and is probed by attempting the operation, never assumed.",
)

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


class MountConfinementUnavailable(NamespaceUnavailable):
    """Filesystem confinement could not be established as declared (RX-08).

    Raised for every failure mode alike -- an unavailable namespace, a declared
    path that does not exist, a bind that did not take effect, a writable
    submount under a protected path. There is deliberately no variant that means
    "confined less than was asked for": the caller refuses the run.
    """


@dataclass(frozen=True)
class MountEntry:
    """One line of ``/proc/self/mountinfo``, reduced to what confinement needs (RX-08)."""

    mount_point: str
    options: str
    fstype: str

    @property
    def option_set(self) -> frozenset[str]:
        """Per-mount options as a set, so ``ro`` can be tested without substring luck."""
        return frozenset(part for part in self.options.split(",") if part)

    @property
    def read_only(self) -> bool:
        """Whether this mount carries the kernel's ``ro`` flag."""
        return "ro" in self.option_set


@dataclass(frozen=True)
class RealisedConfinement:
    """What confinement was *verified in force*, not what was requested (RX-08).

    Returned by :func:`apply_confinement` only after every declared path has been
    found in ``/proc/self/mountinfo`` with the expected flags, so a caller can
    record in an :class:`~retrace_runner.results.IsolationReport` what a verdict
    may honestly claim was enforced.
    """

    readonly_paths: tuple[str, ...]
    hidden_paths: tuple[str, ...]


def confinement_support_reason() -> str | None:
    """Return why mount confinement is structurally unavailable, or ``None`` (RX-08).

    A cheap pre-flight only. ``None`` means "worth attempting", never
    "guaranteed": unprivileged ``CLONE_NEWUSER`` is a kernel policy decision
    (``kernel.unprivileged_userns_clone``, AppArmor and seccomp profiles,
    container runtimes) that no attribute check can predict. The capability
    itself is measured by :func:`probe_confinement_capability`.
    """
    if sys.platform != "linux":
        return f"sys.platform={sys.platform!r} is not linux"
    if not hasattr(os, "unshare"):
        return "this interpreter has no os.unshare (needs CPython 3.12+ on Linux)"
    for flag in ("CLONE_NEWNS", "CLONE_NEWUSER"):
        if not hasattr(os, flag):
            return f"this platform exposes no os.{flag}"
    try:
        with open(
            "/proc/sys/kernel/unprivileged_userns_clone", encoding="ascii"
        ) as handle:
            if handle.read().strip() == "0":
                return "unprivileged user namespaces are disabled by sysctl"
    except OSError:
        pass  # The sysctl is absent on many kernels; absence is not a refusal.
    return None


def parse_mountinfo(text: str) -> tuple[MountEntry, ...]:
    """Parse ``/proc/<pid>/mountinfo`` into :class:`MountEntry` records (RX-08).

    A pure function over text so the verification gate it feeds can be shown to
    reject a bad mount table without having to produce one in the kernel.
    Mount points are unescaped: the kernel renders space, tab, newline and
    backslash as octal escapes, and a protected path containing a space would
    otherwise never match its declaration.
    """
    entries: list[MountEntry] = []
    for line in text.splitlines():
        fields = line.split()
        if "-" not in fields:
            continue
        separator = fields.index("-")
        if separator < 6 or len(fields) < separator + 2:
            continue
        entries.append(
            MountEntry(
                mount_point=_unescape(fields[4]),
                options=fields[5],
                fstype=fields[separator + 1],
            )
        )
    return tuple(entries)


def unprotected_submounts(
    entries: tuple[MountEntry, ...],
    *,
    readonly_paths: tuple[str, ...],
    hidden_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Return mount points under a declared read-only path that are still writable (RX-08).

    ``MS_REMOUNT|MS_RDONLY`` applies to a single mount, so a recursive bind of a
    directory that contains a separate filesystem leaves that filesystem
    writable. Reporting it is the difference between a confinement and a claim
    about one. Declared hidden paths are exempt: an empty ``mode=000`` ``tmpfs``
    is writable by design and holds nothing to protect.
    """
    offenders: set[str] = set()
    for entry in entries:
        if entry.read_only:
            continue
        if not any(_is_within(entry.mount_point, root) for root in readonly_paths):
            continue
        if any(_is_within(entry.mount_point, hidden) for hidden in hidden_paths):
            continue
        offenders.add(entry.mount_point)
    return tuple(sorted(offenders))


def apply_confinement(
    *, readonly_paths: tuple[str, ...], hidden_paths: tuple[str, ...]
) -> RealisedConfinement:
    """Establish the declared confinement in the current mount namespace (RX-08).

    The caller must already have entered a user+mount namespace
    (:func:`retrace_runner.netns.enter_namespaces`). Without one, ``mount(2)``
    fails ``EPERM`` and this refuses -- it cannot succeed by accident on the
    host.

    Steps, in order, each of which raises :class:`MountConfinementUnavailable`
    on failure:

    1. refuse a declaration that confines nothing, or that names a path twice;
    2. detach the mount tree (``MS_REC|MS_PRIVATE`` on ``/``) so nothing done
       here can propagate into the host;
    3. recursively bind each protected path onto itself, then remount it
       read-only;
    4. mount an empty ``tmpfs`` over each secret directory;
    5. **verify** against ``/proc/self/mountinfo`` that every declared path is a
       mount with the flags expected, and that no writable submount survives
       under a protected path.

    Step 5 is what makes the return value evidence rather than an assumption.
    """
    readonly = tuple(_admit_declared_path(path, kind="protected") for path in readonly_paths)
    hidden = tuple(
        _admit_declared_path(path, kind="secret", require_directory=True)
        for path in hidden_paths
    )
    if not readonly and not hidden:
        raise MountConfinementUnavailable(
            "filesystem confinement was requested with no declared paths, which would "
            "confine nothing; declare the protected paths or do not request confinement"
        )
    duplicated = sorted(set(readonly) & set(hidden))
    if duplicated:
        raise MountConfinementUnavailable(
            "a path declared both protected and secret is a contradictory declaration "
            f"(read-only and replaced-by-tmpfs cannot both hold): {duplicated}"
        )

    libc = _libc()
    _mount(libc, None, "/", None, MS_REC | MS_PRIVATE, None, stage="detach mount tree")
    for path in readonly:
        flags = MS_BIND | (MS_REC if os.path.isdir(path) else 0)
        _mount(libc, path, path, None, flags, None, stage=f"bind {path}")
        _mount(
            libc,
            None,
            path,
            None,
            MS_BIND | MS_REMOUNT | MS_RDONLY,
            None,
            stage=f"remount read-only {path}",
        )
    for path in hidden:
        _mount(
            libc,
            TMPFS_FSTYPE.decode(),
            path,
            TMPFS_FSTYPE.decode(),
            0,
            HIDDEN_TMPFS_OPTIONS.decode(),
            stage=f"hide {path}",
        )

    entries = parse_mountinfo(_read_own_mountinfo())
    by_point: dict[str, MountEntry] = {}
    for entry in entries:
        by_point[entry.mount_point] = entry  # last mount at a point is the effective one
    for path in readonly:
        readonly_entry = by_point.get(path)
        if readonly_entry is None or not readonly_entry.read_only:
            raise MountConfinementUnavailable(
                f"the read-only bind for {path!r} is not in force after mounting "
                f"(mountinfo: {readonly_entry!r}); refusing to report a confinement that "
                "was not established"
            )
    for path in hidden:
        hidden_entry = by_point.get(path)
        if hidden_entry is None or hidden_entry.fstype != TMPFS_FSTYPE.decode():
            raise MountConfinementUnavailable(
                f"the empty tmpfs for secret directory {path!r} is not in force after "
                f"mounting (mountinfo: {hidden_entry!r})"
            )
    writable = unprotected_submounts(entries, readonly_paths=readonly, hidden_paths=hidden)
    if writable:
        raise MountConfinementUnavailable(
            "a separate filesystem under a declared protected path is still writable, so "
            f"the protection is incomplete: {list(writable)}. Declare those paths "
            "explicitly or exclude them from the protected set"
        )
    return RealisedConfinement(readonly_paths=readonly, hidden_paths=hidden)


def interpret_probe(payload: dict[str, Any]) -> str | None:
    """Decide whether a probe child demonstrated the capability (RX-08).

    Pure, and separate from running the child, so the gate can be shown to
    reject each way a probe can go wrong -- including the one that matters most:
    a namespace that *failed shut*, denying the control write as well, would
    otherwise make every denial above a false reassurance.

    Returns ``None`` when the capability was demonstrated, or a reason string.
    """
    if payload.get("stage"):
        return f"confinement setup failed at stage {payload['stage']!r}: {payload.get('error')}"
    protected = dict(payload.get("protected_write") or {})
    secret = dict(payload.get("secret_read") or {})
    control = dict(payload.get("control_write") or {})
    if not (protected and secret and control):
        return f"probe child reported an incomplete result: {payload!r}"
    if control.get("outcome") != "ALLOWED":
        return (
            "the probe's control write to an undeclared path was denied, so the namespace "
            "failed shut rather than confining; its denials would prove nothing "
            f"({control!r})"
        )
    if protected.get("outcome") != "DENIED":
        return f"a native write to a read-only bind was not denied: {protected!r}"
    if protected.get("errno") != EROFS:
        return f"a native write was denied, but not by the read-only mount: {protected!r}"
    if secret.get("outcome") != "DENIED":
        return f"a credential under a hidden directory was readable: {secret!r}"
    if secret.get("errno") not in _SECRET_DENIAL_ERRNOS:
        return f"a credential read was denied, but not by the empty tmpfs: {secret!r}"
    return None


def probe_confinement_capability(
    *, timeout_seconds: float = PROBE_TIMEOUT_SECONDS
) -> str | None:
    """Measure the capability by attempting it; return ``None`` or a reason (RX-08).

    Runs this module as a throwaway child, because the attempt is destructive of
    the attempting process's namespaces: ``CLONE_NEWUSER`` cannot be undone, and
    it fails outright in a multi-threaded process. The child confines a
    temporary directory tree and reports three attempts -- a native write to a
    protected file, a read of a canary under a hidden directory, and a control
    write to an undeclared path that must still succeed.

    Nothing outside the temporary tree is touched, and the child's mounts vanish
    with the child: a mount namespace cannot write back into the host's.
    """
    structural = confinement_support_reason()
    if structural is not None:
        return structural
    with tempfile.TemporaryDirectory(prefix="retrace-confinement-probe-") as base:
        protected_dir = os.path.join(base, "protected")
        secret_dir = os.path.join(base, "secret")
        control_dir = os.path.join(base, "control")
        for directory in (protected_dir, secret_dir, control_dir):
            os.mkdir(directory)
        with open(os.path.join(protected_dir, "artefact"), "w", encoding="utf-8") as handle:
            handle.write("probe artefact\n")
        with open(os.path.join(secret_dir, "canary"), "w", encoding="utf-8") as handle:
            handle.write("PROBE-CANARY-NOT-A-REAL-CREDENTIAL\n")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(os.path.dirname(os.path.dirname(__file__)))
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, locally created paths
                [sys.executable, "-m", f"{__package__}.mountns", "--probe", base],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return f"the confinement probe could not be run: {error!r}"
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        if not lines:
            return (
                "the confinement probe produced no verdict "
                f"(exit {completed.returncode}; stderr: {(completed.stderr or '')[-400:]})"
            )
        try:
            payload = json.loads(lines[-1])
        except ValueError:
            return f"the confinement probe produced an unreadable verdict: {lines[-1]!r}"
        if not isinstance(payload, dict):
            return f"the confinement probe produced an unreadable verdict: {payload!r}"
        return interpret_probe(payload)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _unescape(field: str) -> str:
    """Decode the octal escapes the kernel writes into a mountinfo path."""
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), field)


def _is_within(candidate: str, root: str) -> bool:
    """Whether ``candidate`` is ``root`` or lies beneath it, by path components."""
    if candidate == root:
        return True
    return candidate.startswith(root.rstrip("/") + "/")


def _admit_declared_path(path: str, *, kind: str, require_directory: bool = False) -> str:
    """Return a declared path, or refuse it by name (RX-08).

    Admission is strict because a declaration that quietly does not mean what it
    says is a control that quietly does not hold: the path must be absolute and
    already normalised (so it cannot contain ``..``), must exist, must not be a
    symlink anywhere along its length, and -- for a secret directory -- must be
    a directory, because a ``tmpfs`` cannot replace a regular file.
    """
    if not path or not path.startswith("/"):
        raise MountConfinementUnavailable(
            f"declared {kind} path {path!r} is not absolute"
        )
    if path != os.path.normpath(path):
        raise MountConfinementUnavailable(
            f"declared {kind} path {path!r} is not normalised; declare {os.path.normpath(path)!r}"
        )
    if not os.path.exists(path):
        raise MountConfinementUnavailable(
            f"declared {kind} path {path!r} does not exist, so nothing would be confined "
            "there; a mistyped declaration must not read as protection"
        )
    if os.path.realpath(path) != path:
        raise MountConfinementUnavailable(
            f"declared {kind} path {path!r} resolves through a symlink to "
            f"{os.path.realpath(path)!r}; the declared path and the confined path must "
            "be the same path"
        )
    if require_directory and not os.path.isdir(path):
        raise MountConfinementUnavailable(
            f"declared {kind} path {path!r} is not a directory; an empty tmpfs can only "
            "replace a directory"
        )
    return path


def _libc() -> ctypes.CDLL:
    """Return a ``libc`` handle with ``errno`` capture enabled."""
    try:
        return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    except OSError as error:  # pragma: no cover - libc is present on every supported host
        raise MountConfinementUnavailable(f"libc could not be loaded: {error!r}") from error


def _mount(
    libc: ctypes.CDLL,
    source: str | None,
    target: str,
    fstype: str | None,
    flags: int,
    data: str | None,
    *,
    stage: str,
) -> None:
    """Call ``mount(2)``, raising a named refusal that says which stage failed."""
    libc.mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_char_p,
    ]
    libc.mount.restype = ctypes.c_int
    ctypes.set_errno(0)
    status = libc.mount(
        None if source is None else source.encode(),
        target.encode(),
        None if fstype is None else fstype.encode(),
        flags,
        None if data is None else data.encode(),
    )
    if status != 0:
        code = ctypes.get_errno()
        raise MountConfinementUnavailable(
            f"{stage}: mount(2) refused with errno {code} ({os.strerror(code)})"
        )


def _read_own_mountinfo() -> str:
    """Return this process's mount table, or refuse if it cannot be read."""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            return handle.read()
    except OSError as error:  # pragma: no cover - /proc is present on supported hosts
        raise MountConfinementUnavailable(
            f"the mount table could not be read, so the confinement cannot be verified: "
            f"{error!r}"
        ) from error


def _native_attempt(path: str, *, write: bool) -> dict[str, Any]:
    """Attempt ``open(2)`` through ``libc``, bypassing every Python-level guard.

    This is the shape of the bypass the in-process guard cannot see, which is why
    the probe uses it rather than :func:`open`: a confinement measured through a
    call the guard patches would be measuring the guard.
    """
    libc = _libc()
    libc.open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    libc.open.restype = ctypes.c_int
    flags = (os.O_WRONLY | os.O_APPEND) if write else os.O_RDONLY
    ctypes.set_errno(0)
    descriptor = libc.open(path.encode(), flags, 0)
    if descriptor < 0:
        return {"outcome": "DENIED", "errno": ctypes.get_errno()}
    try:
        if write:
            os.write(descriptor, b"PROBE\n")
        else:
            os.read(descriptor, 1)
    finally:
        os.close(descriptor)
    return {"outcome": "ALLOWED", "errno": None}


def _probe_main(base: str) -> int:
    """Confine ``base`` in a fresh namespace and report three attempts as JSON.

    The child half of :func:`probe_confinement_capability`. It prints one JSON
    object and exits non-zero when the capability was not demonstrated, so the
    parent never has to infer a verdict from an exit status alone.
    """
    from .netns import enter_namespaces  # local: keeps the probe child's imports minimal

    protected_dir = os.path.join(base, "protected")
    secret_dir = os.path.join(base, "secret")
    control_dir = os.path.join(base, "control")
    try:
        enter_namespaces(
            os.CLONE_NEWUSER | os.CLONE_NEWNS, capability="filesystem confinement probe"
        )
        apply_confinement(readonly_paths=(protected_dir,), hidden_paths=(secret_dir,))
    except NamespaceUnavailable as error:
        sys.stdout.write(json.dumps({"stage": "setup", "error": str(error)}) + "\n")
        return 1
    payload = {
        "protected_write": _native_attempt(
            os.path.join(protected_dir, "artefact"), write=True
        ),
        "secret_read": _native_attempt(os.path.join(secret_dir, "canary"), write=False),
        "control_write": _native_attempt_create(os.path.join(control_dir, "allowed")),
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    return 0 if interpret_probe(payload) is None else 1


def _native_attempt_create(path: str) -> dict[str, Any]:
    """Create ``path`` natively; the probe's discrimination control.

    An undeclared path must still be writable inside the confinement. If this is
    denied the namespace failed shut and the probe's denials mean nothing, which
    :func:`interpret_probe` checks *before* it looks at any denial.
    """
    libc = _libc()
    libc.open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    libc.open.restype = ctypes.c_int
    ctypes.set_errno(0)
    descriptor = libc.open(path.encode(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if descriptor < 0:
        return {"outcome": "DENIED", "errno": ctypes.get_errno()}
    try:
        os.write(descriptor, b"PROBE\n")
    finally:
        os.close(descriptor)
    return {"outcome": "ALLOWED", "errno": None}


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess by the probe
    if len(sys.argv) != 3 or sys.argv[1] != "--probe":
        sys.stderr.write("usage: python -m retrace_runner.mountns --probe <base-dir>\n")
        raise SystemExit(2)
    raise SystemExit(_probe_main(sys.argv[2]))
