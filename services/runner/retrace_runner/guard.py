"""In-process execution guard: egress denial, write confinement, spawn denial.

This module is deliberately **stdlib-only and import-free of RETRACE**, because
:mod:`retrace_runner.execution` copies its source bytes verbatim into a
throwaway directory as ``sitecustomize.py`` and puts *only that directory* on
the notebook kernel's ``PYTHONPATH``. ``site`` imports ``sitecustomize`` during
interpreter start-up, so the guard is installed in the kernel before a single
notebook cell -- or any library the notebook imports -- gets to run.

WHAT THIS IS, STATED HONESTLY (RX-08)
=====================================
This is a **cooperative, in-process restriction**. It is defence in depth. It is
**not** a kernel boundary, not a container, not a VM, and it is not a security
control you may rely on when executing genuinely hostile code. Specifically:

1. **Same-interpreter code can remove it.** The guard replaces Python-level
   attributes. Notebook code running in the same interpreter can rebind them
   back, or call ``importlib.reload(socket)`` to obtain fresh, unpatched
   functions. Nothing here prevents that, and nothing here detects it.
2. **Native code never sees it.** A C extension, a ``ctypes``/``cffi`` call, a
   Rust or Fortran library, or anything that reaches ``connect(2)`` or
   ``open(2)`` without going through the patched Python callables is entirely
   unaffected. The proof of this is in the runner's own design: the notebook
   kernel's ZeroMQ transport keeps working under full egress denial precisely
   *because* libzmq opens its sockets in C.
3. **Loopback stays reachable under COOPERATIVE.** The denial refuses
   non-loopback destinations only. A service bound to ``127.0.0.1`` on the host
   -- a database, a metadata endpoint, another researcher's notebook server --
   remains reachable. Only ``NetworkIsolation.KERNEL_NAMESPACE`` moves loopback
   into a private namespace where that is no longer true.
4. **Write confinement is path-based, not filesystem-based.** It resolves
   symlinks before deciding, but it only governs the Python callables listed in
   :data:`PATCHED_WRITE_CALLABLES`. ``sqlite3``, ``h5py``, ``numpy.save`` via a
   C path, ``mmap`` writes to an already-open descriptor, and any write through
   an fd obtained before the guard installed are not governed.
5. **An already-open descriptor is not revoked.** The guard checks at open
   time; it does not interpose on ``write(2)``.
6. **``os.fork`` is permitted.** Spawn denial refuses ``exec``-family and
   ``subprocess`` calls, so a fork cannot become a *different* program, but a
   forked copy of the same interpreter still exists.

Treat the guard as a tripwire and a mistake-catcher for *authorised but
untrusted* scientific code. For hostile code, the boundary has to come from the
kernel or the hypervisor, and this build does not have one:
``NetworkIsolation.KERNEL_NAMESPACE`` is a real kernel network boundary but it
is still a shared filesystem and a shared PID namespace.

Requirement coverage: RX-08 (no network, scratch-only writes). The positive
receipt written by :func:`install` is what lets
:mod:`retrace_runner.execution` *verify* that the guard actually installed in
the kernel process rather than assume it, which matters because CPython's
``site`` module swallows exceptions raised by ``sitecustomize``.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import socket
import sys
from typing import Any, Final

__all__ = [
    "ENV_ACTIVE",
    "ENV_NETWORK",
    "ENV_RECEIPT_DIR",
    "ENV_SPAWN",
    "ENV_WRITE_ROOTS",
    "GUARD_LIMITS",
    "NETWORK_DENY_NON_LOOPBACK",
    "NETWORK_OFF",
    "PATCHED_WRITE_CALLABLES",
    "RetraceGuardDenied",
    "RetraceGuardInstallFailed",
    "RetraceNetworkDenied",
    "RetraceSpawnDenied",
    "RetraceWriteDenied",
    "install",
    "install_from_environment",
    "receipt_filename",
    "target_is_denied",
]

ENV_ACTIVE: Final[str] = "RETRACE_GUARD_ACTIVE"
ENV_WRITE_ROOTS: Final[str] = "RETRACE_GUARD_WRITE_ROOTS"
ENV_NETWORK: Final[str] = "RETRACE_GUARD_NETWORK"
ENV_SPAWN: Final[str] = "RETRACE_GUARD_SPAWN"
ENV_RECEIPT_DIR: Final[str] = "RETRACE_GUARD_RECEIPT_DIR"

NETWORK_DENY_NON_LOOPBACK: Final[str] = "deny-non-loopback"
NETWORK_OFF: Final[str] = "off"

SPAWN_DENY: Final[str] = "deny"
SPAWN_ALLOW: Final[str] = "allow"

GUARD_LIMITS: Final[tuple[str, ...]] = (
    "Cooperative only: code in the same interpreter can rebind the patched "
    "callables or reload the module to recover unpatched ones.",
    "Native code (ctypes/cffi/C extensions) reaches connect(2) and open(2) "
    "without passing through this guard and is unaffected by it.",
    "Under COOPERATIVE egress denial, loopback destinations remain reachable; "
    "only a kernel network namespace changes that.",
    "Write confinement governs the listed Python callables at open time. It "
    "does not interpose on write(2) and does not govern C-level file I/O.",
    "File descriptors opened before installation are not revoked.",
)

PATCHED_WRITE_CALLABLES: Final[tuple[str, ...]] = (
    "builtins.open",
    "io.open",
    "os.open",
    "os.mkdir",
    "os.makedirs",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.rename",
    "os.replace",
    "os.truncate",
    "os.symlink",
    "os.link",
    "os.chmod",
    "os.utime",
)

_WRITE_MODE_CHARACTERS: Final[frozenset[str]] = frozenset("wax+")
_WRITE_OPEN_FLAGS: Final[int] = (
    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
)

_LOOPBACK_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {"", "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

_INSTALLED: dict[str, Any] = {}


class RetraceGuardDenied(PermissionError):
    """Base class for an action the in-process guard refused (RX-08).

    Derives from :class:`PermissionError` so that notebook code which already
    handles permission failures behaves sensibly, while the distinct class name
    keeps the refusal attributable to the guard in a traceback.
    """


class RetraceNetworkDenied(RetraceGuardDenied):
    """A non-loopback network destination was refused (RX-08)."""


class RetraceWriteDenied(RetraceGuardDenied):
    """A write outside the declared scratch roots was refused (RX-08)."""


class RetraceSpawnDenied(RetraceGuardDenied):
    """Spawning another program was refused (RX-08).

    Spawning is refused because a child program would run outside every patched
    callable and therefore outside both the egress denial and the write
    confinement.
    """


class RetraceGuardInstallFailed(RuntimeError):
    """The guard could not be installed, so the interpreter must not continue."""


def receipt_filename(pid: int) -> str:
    """Return the receipt filename a process of ``pid`` writes on install (RX-08)."""
    return f"{pid}.json"


def _real(path: str) -> str:
    """Resolve ``path`` to an absolute, symlink-free string without opening it."""
    return os.path.realpath(os.path.abspath(path))


def _is_within(candidate: str, root: str) -> bool:
    """Return whether ``candidate`` is ``root`` or lies beneath it."""
    if candidate == root:
        return True
    return candidate.startswith(root.rstrip(os.sep) + os.sep)


def _mode_writes(mode: object) -> bool:
    """Return whether an ``open`` mode string requests any kind of write."""
    if not isinstance(mode, str):
        return True
    return any(character in _WRITE_MODE_CHARACTERS for character in mode)


def target_is_denied(family: int | None, address: object) -> bool:
    """Return whether ``address`` is a denied network destination (RX-08).

    Only ``AF_INET``/``AF_INET6`` destinations are considered: a ``AF_UNIX``
    peer is not egress, and the notebook kernel's own transport must keep
    working. A destination is denied unless it is a loopback literal or one of
    the loopback hostnames in :data:`_LOOPBACK_HOSTNAMES`; a non-numeric
    hostname is denied because resolving it is itself egress.

    Exposed as a public function so the decision can be unit-tested directly in
    both directions -- a deny rule that has only ever been seen to allow is not
    evidence that it denies.
    """
    if family is not None and family not in (socket.AF_INET, socket.AF_INET6):
        return False
    host: object = address
    if isinstance(address, (tuple, list)):
        if not address:
            return True
        host = address[0]
    if host is None:
        return False
    if not isinstance(host, (str, bytes, bytearray)):
        return True
    text = host.decode("utf-8", "replace") if isinstance(host, (bytes, bytearray)) else host
    if text.lower() in _LOOPBACK_HOSTNAMES:
        return False
    import ipaddress

    try:
        return not ipaddress.ip_address(text.strip("[]")).is_loopback
    except ValueError:
        # A name, not a literal: resolving it would be egress.
        return True


def _install_network_denial() -> None:
    """Refuse Python-level connections and name resolution off the loopback."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if target_is_denied(getattr(self, "family", None), address):
            raise RetraceNetworkDenied(
                f"network egress denied by the RETRACE runner guard: connect to {address!r}"
            )
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if target_is_denied(getattr(self, "family", None), address):
            raise RetraceNetworkDenied(
                f"network egress denied by the RETRACE runner guard: connect_ex to {address!r}"
            )
        return original_connect_ex(self, address)

    def guarded_sendto(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        address = args[-1] if args else kwargs.get("address")
        if target_is_denied(getattr(self, "family", None), address):
            raise RetraceNetworkDenied(
                f"network egress denied by the RETRACE runner guard: sendto {address!r}"
            )
        return original_sendto(self, *args, **kwargs)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if target_is_denied(socket.AF_INET, address):
            raise RetraceNetworkDenied(
                "network egress denied by the RETRACE runner guard: "
                f"create_connection to {address!r}"
            )
        return _INSTALLED["create_connection"](address, *args, **kwargs)

    def guarded_getaddrinfo(host: Any, port: Any = None, *args: Any, **kwargs: Any) -> Any:
        if target_is_denied(socket.AF_INET, host):
            raise RetraceNetworkDenied(
                f"name resolution denied by the RETRACE runner guard: getaddrinfo {host!r}"
            )
        return _INSTALLED["getaddrinfo"](host, port, *args, **kwargs)

    def guarded_gethostbyname(host: Any) -> Any:
        raise RetraceNetworkDenied(
            f"name resolution denied by the RETRACE runner guard: gethostbyname {host!r}"
        )

    def guarded_gethostbyname_ex(host: Any) -> Any:
        raise RetraceNetworkDenied(
            f"name resolution denied by the RETRACE runner guard: gethostbyname_ex {host!r}"
        )

    _INSTALLED["create_connection"] = socket.create_connection
    _INSTALLED["getaddrinfo"] = socket.getaddrinfo
    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.socket.sendto = guarded_sendto  # type: ignore[assignment]
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = guarded_gethostbyname
    socket.gethostbyname_ex = guarded_gethostbyname_ex


def _install_write_confinement(write_roots: tuple[str, ...]) -> None:
    """Refuse writes whose resolved path lies outside ``write_roots`` (RX-08)."""
    roots = tuple(_real(root) for root in write_roots)

    def permitted(path: object) -> bool:
        if isinstance(path, int):
            # An existing descriptor; it was admitted when it was opened.
            return True
        if isinstance(path, (bytes, bytearray)):
            path = path.decode("utf-8", "replace")
        if not isinstance(path, str):
            path = str(path)
        resolved = _real(path)
        return any(_is_within(resolved, root) for root in roots)

    def deny(path: object, action: str) -> None:
        raise RetraceWriteDenied(
            f"write confinement denied by the RETRACE runner guard: {action} {path!r} is "
            f"outside the scratch roots {roots!r}"
        )

    original_open = builtins.open
    original_os_open = os.open

    def guarded_open(file: Any, mode: Any = "r", *args: Any, **kwargs: Any) -> Any:
        if _mode_writes(mode) and not permitted(file):
            deny(file, "open")
        return original_open(file, mode, *args, **kwargs)

    def guarded_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> Any:
        if (flags & _WRITE_OPEN_FLAGS) and not permitted(path):
            deny(path, "os.open")
        return original_os_open(path, flags, *args, **kwargs)

    builtins.open = guarded_open
    io.open = guarded_open
    os.open = guarded_os_open

    def wrap_single(name: str) -> None:
        original = getattr(os, name, None)
        if original is None:  # pragma: no cover - platform dependent
            return

        def guarded(path: Any, *args: Any, **kwargs: Any) -> Any:
            if not permitted(path):
                deny(path, f"os.{name}")
            return original(path, *args, **kwargs)

        setattr(os, name, guarded)

    def wrap_pair(name: str) -> None:
        original = getattr(os, name, None)
        if original is None:  # pragma: no cover - platform dependent
            return

        def guarded(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            if not permitted(dst):
                deny(dst, f"os.{name}")
            return original(src, dst, *args, **kwargs)

        setattr(os, name, guarded)

    for name in ("mkdir", "makedirs", "remove", "unlink", "rmdir", "truncate", "chmod", "utime"):
        wrap_single(name)
    for name in ("rename", "replace", "link", "symlink"):
        wrap_pair(name)


def _install_spawn_denial() -> None:
    """Refuse spawning another program from inside the guarded interpreter (RX-08)."""

    def denied(action: str) -> Any:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            raise RetraceSpawnDenied(
                f"process spawning denied by the RETRACE runner guard: {action}. A spawned "
                "program would run outside the egress denial and the write confinement."
            )

        return guarded

    for name in (
        "system",
        "posix_spawn",
        "posix_spawnp",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    ):
        if hasattr(os, name):
            setattr(os, name, denied(f"os.{name}"))

    import subprocess  # noqa: S404 - patched here precisely so it cannot be used

    class DeniedPopen(subprocess.Popen):
        """A ``Popen`` that refuses to start anything (RX-08)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RetraceSpawnDenied(
                "process spawning denied by the RETRACE runner guard: subprocess.Popen"
            )

    subprocess.Popen = DeniedPopen  # type: ignore[misc]


def _write_receipt(receipt_dir: str, payload: dict[str, Any]) -> None:
    """Write the positive install receipt before any write patching is applied.

    The receipt is how :mod:`retrace_runner.execution` *verifies* that the guard
    installed inside the kernel process. CPython's ``site`` module swallows
    exceptions from ``sitecustomize``, so absence of this file is the only
    reliable signal that the guard did not run.
    """
    os.makedirs(receipt_dir, exist_ok=True)
    path = os.path.join(receipt_dir, receipt_filename(os.getpid()))
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def install(
    *,
    write_roots: tuple[str, ...],
    network: str,
    spawn: str,
    receipt_dir: str | None = None,
) -> dict[str, Any]:
    """Install the in-process guard and return the receipt payload (RX-08).

    Order matters: the receipt is written *before* write confinement is applied,
    because the receipt directory is deliberately outside the notebook's
    writable roots. Installing twice is a no-op; the first receipt stands.

    Raises
    ------
    RetraceGuardInstallFailed:
        If any requested layer cannot be installed. The caller
        (:func:`install_from_environment`) turns this into interpreter
        termination rather than letting a half-guarded kernel continue.
    """
    if _INSTALLED.get("receipt"):
        return dict(_INSTALLED["receipt"])
    if network not in (NETWORK_DENY_NON_LOOPBACK, NETWORK_OFF):
        raise RetraceGuardInstallFailed(f"unknown network guard mode {network!r}")
    if spawn not in (SPAWN_DENY, SPAWN_ALLOW):
        raise RetraceGuardInstallFailed(f"unknown spawn guard mode {spawn!r}")
    if not write_roots:
        raise RetraceGuardInstallFailed("write confinement requires at least one scratch root")

    receipt = {
        "pid": os.getpid(),
        "python_version": sys.version.split()[0],
        "network": network,
        "spawn": spawn,
        "write_roots": [_real(root) for root in write_roots],
        "patched_write_callables": list(PATCHED_WRITE_CALLABLES),
        "cooperative": True,
    }
    if receipt_dir:
        _write_receipt(receipt_dir, receipt)
    if network == NETWORK_DENY_NON_LOOPBACK:
        _install_network_denial()
    if spawn == SPAWN_DENY:
        _install_spawn_denial()
    _install_write_confinement(write_roots)
    _INSTALLED["receipt"] = receipt
    return dict(receipt)


def install_from_environment() -> dict[str, Any] | None:
    """Install the guard from ``RETRACE_GUARD_*`` variables, or do nothing (RX-08).

    Returns ``None`` when :data:`ENV_ACTIVE` is unset, so a copy of this file
    lying on some unrelated ``PYTHONPATH`` changes no behaviour at all.

    If the guard *is* requested and cannot be installed, the interpreter is
    terminated with :data:`GUARD_INSTALL_FAILURE_EXIT`. That is deliberate:
    ``site.execsitecustomize`` catches and discards exceptions, so raising here
    would leave an unguarded kernel running.
    """
    if os.environ.get(ENV_ACTIVE) != "1":
        return None
    roots = tuple(
        part for part in os.environ.get(ENV_WRITE_ROOTS, "").split(os.pathsep) if part
    )
    try:
        return install(
            write_roots=roots,
            network=os.environ.get(ENV_NETWORK, NETWORK_DENY_NON_LOOPBACK),
            spawn=os.environ.get(ENV_SPAWN, SPAWN_DENY),
            receipt_dir=os.environ.get(ENV_RECEIPT_DIR) or None,
        )
    except Exception as error:  # noqa: BLE001 - must not leave an unguarded kernel alive
        sys.stderr.write(f"RETRACE runner guard failed to install: {error!r}\n")
        sys.stderr.flush()
        os._exit(GUARD_INSTALL_FAILURE_EXIT)


GUARD_INSTALL_FAILURE_EXIT: Final[int] = 44
"""Exit status used when the guard cannot install. Fail closed, never fail open."""


install_from_environment()
