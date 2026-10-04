"""Service configuration, and the settings that must never have a default (RX-45).

THREE SETTINGS DELIBERATELY HAVE NO USABLE DEFAULT.

``cors_allowed_origins`` is empty unless configured, and ``"*"`` is REFUSED at
construction rather than warned about. A wildcard origin with credentialed
requests is not merely loose: browsers refuse the combination, so a developer
who sets it gets a confusing client-side failure and reaches for
``allow_credentials=False``, which breaks the cookie session instead. Refusing
the value at construction turns that into one clear error at startup.

``oidc_issuer`` and ``oidc_client_id`` are ``None`` unless configured, and the
sign-in route reports ``NEEDS_CONFIGURATION`` while they are. There is no
fallback local credential: see
:class:`retrace_api.web.errors.IdentityProviderNotConfigured`.

``cookie_secure`` defaults to **True**. The usual shortcut is to default it off
for local development and turn it on in production, which inverts the failure:
the insecure setting becomes the one nobody notices. Here a plain-HTTP
development host must opt out explicitly, and the opt-out is recorded on the
config object where a test can assert it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "IDEMPOTENCY_HEADER_NAME",
    "SESSION_COOKIE_NAME",
    "ApiConfig",
    "ConfigurationError",
    "config_from_env",
]

#: Session cookie. HttpOnly, so script cannot read it.
SESSION_COOKIE_NAME: Final = "retrace_session"
#: CSRF cookie. Readable by script ON PURPOSE - the double-submit pattern needs
#: the client to be able to copy it into a header. It is not a credential on its
#: own: it authorises nothing without the HttpOnly session cookie beside it.
CSRF_COOKIE_NAME: Final = "retrace_csrf"
CSRF_HEADER_NAME: Final = "x-retrace-csrf"
IDEMPOTENCY_HEADER_NAME: Final = "idempotency-key"

_SAMESITE_VALUES: Final = ("lax", "strict")


class ConfigurationError(RuntimeError):
    """A configuration value is absent or unusable, so the app will not start."""


@dataclass(frozen=True)
class ApiConfig:
    """Settings for one API instance (RX-45, RX-47).

    Frozen: a request handler must not be able to widen CORS or clear the secure
    cookie flag at runtime.
    """

    #: Exact origins permitted by CORS. Empty means cross-origin browser access
    #: is not permitted at all, which is the correct default for an API with no
    #: configured front end.
    cors_allowed_origins: tuple[str, ...] = ()
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict"] = "strict"
    #: Session lifetime. Short by default; the session is server-managed, so
    #: extending it is a server-side decision and not a cookie expiry a client
    #: can edit.
    session_ttl_seconds: int = 3600
    #: Maximum sessions held in memory, so an unauthenticated flood cannot grow
    #: the store without bound. See `SessionStore` for what eviction means here.
    max_sessions: int = 10_000
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    #: Root for the per-tenant quarantine, content-addressed store, approval
    #: ledger and evidence areas. ``None`` means no durable area is configured
    #: and the routes that need one refuse with NEEDS_CONFIGURATION.
    storage_root: Path | None = None
    #: Runtime database URL. ``None`` selects the in-memory repository, which is
    #: what the unit suite uses and which is NOT a substitute for the RLS proof.
    database_url: str | None = None
    #: Recorded so a test can assert that an insecure cookie was an explicit
    #: choice rather than a default.
    insecure_cookie_opt_out: bool = field(default=False)

    def __post_init__(self) -> None:
        for origin in self.cors_allowed_origins:
            if origin.strip() in {"*", ""} or origin.strip().endswith("*"):
                raise ConfigurationError(
                    f"CORS origin {origin!r} is a wildcard; RX-45 requires an exact "
                    "allowlist, and a wildcard cannot be combined with credentialed "
                    "requests in any case"
                )
            if "://" not in origin:
                raise ConfigurationError(
                    f"CORS origin {origin!r} has no scheme; an origin is "
                    "scheme://host[:port], and a bare host matches nothing"
                )
        if self.cookie_samesite not in _SAMESITE_VALUES:
            raise ConfigurationError(
                f"cookie_samesite={self.cookie_samesite!r} is not one of {_SAMESITE_VALUES}; "
                "'none' is refused because it would permit a cross-site mutation to "
                "carry the session cookie"
            )
        if self.session_ttl_seconds <= 0:
            raise ConfigurationError("session_ttl_seconds must be positive")
        if self.max_sessions <= 0:
            raise ConfigurationError("max_sessions must be positive")
        if not self.cookie_secure and not self.insecure_cookie_opt_out:
            raise ConfigurationError(
                "cookie_secure=False requires insecure_cookie_opt_out=True; serving a "
                "session cookie over plain HTTP is a decision that has to be recorded, "
                "not a default that nobody notices"
            )

    @property
    def identity_provider_configured(self) -> bool:
        """Whether a real sign-in could be attempted (RX-45)."""
        return bool(self.oidc_issuer and self.oidc_client_id)

    def missing_identity_settings(self) -> tuple[str, ...]:
        """Names of the absent identity settings, for the refusal body."""
        missing = []
        if not self.oidc_issuer:
            missing.append("RETRACE_OIDC_ISSUER")
        if not self.oidc_client_id:
            missing.append("RETRACE_OIDC_CLIENT_ID")
        return tuple(missing)


def config_from_env(env: Mapping[str, str] | None = None) -> ApiConfig:
    """Build an :class:`ApiConfig` from the environment (RX-45).

    Unset is unset: no value here is guessed. An unparseable integer raises
    rather than falling back, because a silently defaulted session lifetime is
    a security property nobody chose.
    """
    source = os.environ if env is None else env
    raw_origins = source.get("RETRACE_CORS_ALLOWED_ORIGINS", "")
    origins = tuple(part.strip() for part in raw_origins.split(",") if part.strip())
    secure = source.get("RETRACE_COOKIE_SECURE", "true").strip().lower() != "false"
    samesite_raw = source.get("RETRACE_COOKIE_SAMESITE", "strict").strip().lower()
    if samesite_raw not in _SAMESITE_VALUES:
        raise ConfigurationError(
            f"RETRACE_COOKIE_SAMESITE={samesite_raw!r} is not one of {_SAMESITE_VALUES}"
        )
    samesite: Literal["lax", "strict"] = "lax" if samesite_raw == "lax" else "strict"
    try:
        ttl = int(source.get("RETRACE_SESSION_TTL_SECONDS", "3600"))
    except ValueError as exc:
        raise ConfigurationError("RETRACE_SESSION_TTL_SECONDS is not an integer") from exc
    root = source.get("RETRACE_STORAGE_ROOT")
    return ApiConfig(
        cors_allowed_origins=origins,
        cookie_secure=secure,
        cookie_samesite=samesite,
        session_ttl_seconds=ttl,
        oidc_issuer=source.get("RETRACE_OIDC_ISSUER") or None,
        oidc_client_id=source.get("RETRACE_OIDC_CLIENT_ID") or None,
        storage_root=Path(root) if root else None,
        database_url=source.get("RETRACE_DATABASE_URL") or None,
        insecure_cookie_opt_out=(
            source.get("RETRACE_INSECURE_COOKIE_OPT_OUT", "").strip().lower() == "true"
        ),
    )
