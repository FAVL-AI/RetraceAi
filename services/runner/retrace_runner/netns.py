"""Kernel-level network isolation via an unprivileged user+network namespace.

This is the one isolation layer in the runner that is a *real kernel boundary*
rather than a cooperative restriction (RX-08). ``unshare(CLONE_NEWUSER |
CLONE_NEWNET)`` gives the child a fresh network namespace containing nothing but
a down loopback device, so there is no route off the host for any code in that
process tree -- native or otherwise.

What it still does **not** isolate, stated plainly:

* the filesystem (same mount namespace, same files, same ``/proc``);
* the PID namespace (the child can see and signal host processes it owns);
* CPU, and anything reachable through an already-open descriptor;
* a unix-domain socket path on the shared filesystem.

Availability is not assumed. Unprivileged ``CLONE_NEWUSER`` is a kernel policy
decision (``kernel.unprivileged_userns_clone``, AppArmor/seccomp profiles,
container runtimes) and ``CLONE_NEWUSER`` additionally fails with ``EINVAL`` in
a multi-threaded process. :func:`enter_private_network_namespace` therefore
raises and the caller refuses the run rather than falling back (RX-08).
"""

from __future__ import annotations

import fcntl
import os
import socket
import struct
from typing import Final

__all__ = [
    "NAMESPACE_LIMITS",
    "NetworkNamespaceUnavailable",
    "bring_loopback_up",
    "enter_private_network_namespace",
    "namespace_support_reason",
]

_SIOCGIFFLAGS: Final[int] = 0x8913
_SIOCSIFFLAGS: Final[int] = 0x8914
_IFF_UP: Final[int] = 0x1
_IFREQ_PAD: Final[int] = 40 - 18

NAMESPACE_LIMITS: Final[tuple[str, ...]] = (
    "A private network namespace isolates the network only. The filesystem, "
    "the PID namespace and /proc are shared with the host.",
    "Availability depends on kernel policy for unprivileged user namespaces; "
    "it cannot be assumed and is never silently skipped.",
    "CLONE_NEWUSER fails in a multi-threaded process, so the namespace must be "
    "entered before any thread, kernel or event loop starts.",
)


class NetworkNamespaceUnavailable(RuntimeError):
    """A private network namespace could not be created (RX-08)."""


def namespace_support_reason() -> str | None:
    """Return why namespace isolation is unavailable, or ``None`` if it looks available.

    A cheap pre-flight check only: it reports a *structural* reason (wrong
    platform, no ``os.unshare``). It cannot predict a kernel policy refusal, so
    ``None`` means "worth attempting", never "guaranteed".
    """
    if os.name != "posix":
        return f"os.name={os.name!r} is not posix"
    if not hasattr(os, "unshare"):
        return "this interpreter has no os.unshare (needs CPython 3.12+ on Linux)"
    if not hasattr(os, "CLONE_NEWNET") or not hasattr(os, "CLONE_NEWUSER"):
        return "this platform exposes no CLONE_NEWNET/CLONE_NEWUSER constants"
    return None


def enter_private_network_namespace() -> dict[str, str]:
    """Move the calling process into a new user+network namespace (RX-08).

    Writes an identity uid/gid mapping so file ownership keeps working, and
    denies ``setgroups`` first as the kernel requires for an unprivileged
    mapping. Returns a small record of what was established, for the
    environment manifest.

    Raises
    ------
    NetworkNamespaceUnavailable:
        If the namespace cannot be created or the mappings cannot be written.
        The caller must refuse the run; there is no partial success here.
    """
    reason = namespace_support_reason()
    if reason is not None:
        raise NetworkNamespaceUnavailable(reason)
    uid, gid = os.getuid(), os.getgid()
    try:
        os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
    except OSError as error:
        raise NetworkNamespaceUnavailable(
            f"unshare(CLONE_NEWUSER|CLONE_NEWNET) refused: {error}"
        ) from error
    try:
        with open("/proc/self/setgroups", "w", encoding="ascii") as handle:
            handle.write("deny")
        with open("/proc/self/uid_map", "w", encoding="ascii") as handle:
            handle.write(f"{uid} {uid} 1")
        with open("/proc/self/gid_map", "w", encoding="ascii") as handle:
            handle.write(f"{gid} {gid} 1")
    except OSError as error:
        raise NetworkNamespaceUnavailable(
            f"namespace created but uid/gid mapping failed: {error}"
        ) from error
    return {"mode": "user+net", "uid_map": f"{uid} {uid} 1", "gid_map": f"{gid} {gid} 1"}


def bring_loopback_up() -> bool:
    """Bring ``lo`` up inside the current network namespace (RX-08).

    The notebook kernel's ZeroMQ transport binds ``127.0.0.1``, and a fresh
    namespace starts with loopback *down*. Returns whether the interface was
    brought up; a failure is returned rather than raised because the caller may
    legitimately choose an inter-process transport that does not need it.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            request = struct.pack("16sh", b"lo", 0) + b"\x00" * _IFREQ_PAD
            # ioctl returns the whole 40-byte ifreq; only the leading
            # name+flags pair is meaningful, so the tail must be sliced off
            # before unpacking or struct refuses the buffer length.
            answer = fcntl.ioctl(probe.fileno(), _SIOCGIFFLAGS, request)
            flags = struct.unpack("16sh", answer[:18])[1] | _IFF_UP
            fcntl.ioctl(
                probe.fileno(),
                _SIOCSIFFLAGS,
                struct.pack("16sh", b"lo", flags) + b"\x00" * _IFREQ_PAD,
            )
    except OSError:
        return False
    return True
