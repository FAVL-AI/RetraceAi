"""HTTP routers for the documented journey (RX-20, RX-44).

One module per stage of the journey, in the order the journey runs:

    auth        -> sessions (and the NEEDS_CONFIGURATION sign-in)
    projects    -> the tenant-owned container
    uploads     -> admission and snapshot promotion (RX-42, RX-01)
    contracts   -> draft then ledger-established approval (RX-03, RX-04, RX-05)
    proposals   -> reviewable patch, review, exact approval (RX-06)
    runs        -> the execution gate (RX-08, threat T2)
    verification-> read-only reports (RX-11, RX-12)
    evidence    -> authorised export and provenance-preserving import (RX-15, RX-16)

No router here reads a tenant or an actor from the request. Every one of them
takes `retrace_api.web.dependencies.authorised_workspace`, which is the single
place those two values are established.
"""

from __future__ import annotations

__all__: list[str] = []
