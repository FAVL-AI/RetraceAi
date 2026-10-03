"""A kernel-enforced read-only confinement probe, for T2 evidence.

WHY THIS EXISTS. `RepairAuthority` is a Python path guard: it refuses writes a
repair provider asks it about. It cannot refuse a write that never asks. The
threat model records that as T2, and the project invariants recovered from the
blueprint are explicit that separation must come from "separate storage,
credentials and execution roles", not from prompts or in-process checks.

So this module answers two questions with real processes, not assertions:

1. What denies a bypass attempt TODAY? (Often: nothing.)
2. Is a kernel-enforced denial achievable on this host at all?

On (2) the answer is yes, and narrower than it may look. This workstation has no
usable sudo and cannot `chown`, so a DISTINCT OS IDENTITY is unavailable and
credential separation by file ownership is impossible here. But unprivileged
user namespaces are enabled (`/proc/sys/kernel/unprivileged_userns_clone` = 1)
and `CLONE_NEWUSER|CLONE_NEWNS` succeeds, so a child can be given a mount
namespace in which protected paths are bind-mounted read-only. That is enforced
by the kernel and applies to every write path - `open`, `os.open`, a C
extension, a subprocess - not only to the ones that consult a guard.

Scope limits, stated plainly: this confines a COOPERATIVELY LAUNCHED child. It
is not protection against a compromised host, it does not separate credentials,
and the infrastructure-administrator trust boundary is unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
MS_BIND = 0x1000
MS_REC = 0x4000
MS_PRIVATE = 0x40000
MS_REMOUNT = 0x20
MS_RDONLY = 0x1


def namespace_support() -> str | None:
    """Return why confinement is unavailable, or None if it looks available."""
    if sys.platform != "linux":
        return f"not linux: {sys.platform}"
    if not hasattr(os, "unshare"):
        return "interpreter has no os.unshare (needs CPython 3.12+)"
    try:
        flag = Path("/proc/sys/kernel/unprivileged_userns_clone")
        if flag.is_file() and flag.read_text().strip() == "0":
            return "unprivileged user namespaces are disabled by sysctl"
    except OSError:
        pass
    return None


_CHILD = textwrap.dedent(
    '''
    import ctypes, ctypes.util, json, os, sys

    CLONE_NEWNS, CLONE_NEWUSER = 0x00020000, 0x10000000
    MS_BIND, MS_REC, MS_PRIVATE, MS_REMOUNT, MS_RDONLY = 0x1000, 0x4000, 0x40000, 0x20, 0x1

    payload = json.loads(sys.argv[1])
    confine = payload["confine"]
    readonly_paths = payload["readonly"]
    hidden_paths = payload["hidden"]
    attempt = payload["attempt"]
    target = payload["target"]

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

    def fail(stage, err):
        print(json.dumps({"stage": stage, "errno": err, "outcome": "SETUP_FAILED"}))
        sys.exit(3)

    if confine:
        uid, gid = os.getuid(), os.getgid()
        try:
            os.unshare(CLONE_NEWUSER | CLONE_NEWNS)
        except OSError as e:
            fail("unshare", e.errno)
        try:
            # setgroups must be denied before an unprivileged gid map is accepted.
            open("/proc/self/setgroups", "w").write("deny")
            open("/proc/self/uid_map", "w").write(f"0 {uid} 1")
            open("/proc/self/gid_map", "w").write(f"0 {gid} 1")
        except OSError as e:
            fail("idmap", e.errno)
        # Detach the mount tree so our changes cannot escape into the host.
        if libc.mount(None, b"/", None, MS_REC | MS_PRIVATE, None) != 0:
            fail("make-private", ctypes.get_errno())
        for p in readonly_paths:
            b = p.encode()
            if libc.mount(b, b, None, MS_BIND | MS_REC, None) != 0:
                fail("bind", ctypes.get_errno())
            if libc.mount(None, b, None, MS_BIND | MS_REMOUNT | MS_RDONLY, None) != 0:
                fail("remount-ro", ctypes.get_errno())
        for p in hidden_paths:
            # An empty tmpfs over the directory: the real contents are not merely
            # unwritable, they are not reachable. Read-only is the wrong tool for a
            # secret - a credential the worker can read is a credential it can use.
            if libc.mount(b"tmpfs", p.encode(), b"tmpfs", 0, b"mode=000,size=4k") != 0:
                fail("hide", ctypes.get_errno())

    try:
        if attempt == "write":
            with open(target, "a", encoding="utf-8") as fh:
                fh.write("TAMPERED\\n")
            outcome = "ALLOWED"
        elif attempt == "read":
            with open(target, encoding="utf-8") as fh:
                fh.read()
            outcome = "ALLOWED"
        elif attempt == "unlink":
            os.unlink(target)
            outcome = "ALLOWED"
        elif attempt == "os_open_write":
            fd = os.open(target, os.O_WRONLY | os.O_APPEND)
            os.write(fd, b"TAMPERED\\n")
            os.close(fd)
            outcome = "ALLOWED"
        else:
            outcome = "UNKNOWN_ATTEMPT"
        print(json.dumps({"outcome": outcome, "errno": None}))
    except OSError as e:
        print(json.dumps({"outcome": "DENIED", "errno": e.errno, "error": e.strerror}))
    '''
).strip()


def attempt(
    *,
    attempt: str,
    target: Path,
    confine: bool,
    readonly: list[Path] | None = None,
    hidden: list[Path] | None = None,
) -> dict:
    """Run one bypass attempt in a child process. Returns its JSON verdict.

    The child never consults RepairAuthority. That is the point: a guard the
    caller can decline to call is not an enforcement boundary.
    """
    payload = json.dumps(
        {
            "confine": confine,
            "readonly": [str(p) for p in (readonly or [])],
            "hidden": [str(p) for p in (hidden or [])],
            "attempt": attempt,
            "target": str(target),
        }
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv, locally constructed payload
        [sys.executable, "-c", _CHILD, payload],
        capture_output=True,
        text=True,
        timeout=120,
    )
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return {"outcome": "NO_OUTPUT", "stderr": proc.stderr[-800:]}
    return json.loads(line[-1])
