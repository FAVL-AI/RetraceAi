"""Session and CSRF cookie attributes (RX-45).

THE SESSION COOKIE IS HttpOnly AND THE CSRF COOKIE IS NOT, AND THAT IS THE POINT.

The session cookie is the credential, so script must not be able to read it:
``HttpOnly``. The CSRF cookie exists precisely so that the page's own script CAN
read it and copy it into a header, which is what makes the double-submit
comparison meaningful - so it is deliberately not ``HttpOnly``. It is not a
credential: on its own it authorises nothing, because every protected route
requires the session cookie as well.

``Secure`` and ``SameSite`` are applied to both. ``SameSite=strict`` by default,
which means a cross-site navigation does not carry the session at all - the
strongest of the three settings, and affordable here because this is an API
rather than a site users arrive at from elsewhere. ``none`` is refused by
:class:`~retrace_api.web.config.ApiConfig`.

``Max-Age`` is set from the server's own TTL so a client expires the cookie at
roughly the time the server expires the record. The server-side record is still
the authority: an edited cookie expiry buys nothing, because
:meth:`SessionStore.resolve` checks the stored ``expires_at``.
"""

from __future__ import annotations

from fastapi import Response
from retrace_api.web.config import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, ApiConfig
from retrace_api.web.identity import SessionRecord

__all__ = ["apply_session_cookies", "clear_session_cookies"]


def apply_session_cookies(
    response: Response, record: SessionRecord, config: ApiConfig
) -> Response:
    """Set the session and CSRF cookies for ``record`` (RX-45)."""
    max_age = int((record.expires_at - record.created_at).total_seconds())
    response.set_cookie(
        SESSION_COOKIE_NAME,
        record.session_id,
        max_age=max_age,
        httponly=True,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        record.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        path="/",
    )
    return response


def clear_session_cookies(response: Response, config: ApiConfig) -> Response:
    """Remove both cookies.

    Both are cleared with the same attributes they were set with; a cookie
    deleted without matching ``path`` and ``samesite`` can be left in place by
    the browser, which would leave a stale credential in the client after an
    explicit sign-out.
    """
    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(
            name, path="/", secure=config.cookie_secure, samesite=config.cookie_samesite
        )
    return response
