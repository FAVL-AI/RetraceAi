"""Locale registry - the single lookup point for locale facts (RX-26, RX-27, RX-28).

``specs/locales.json`` is the ONLY source of truth for which locales exist, their
writing direction and their declared CLDR plural categories. This module loads
that file once and every other unit in the package asks this module instead of
carrying a list of its own.

WHY THERE IS NO HARDCODED LOCALE LIST ANYWHERE ELSE
    The tag scheme is under reconciliation: the upstream specification writes
    region-qualified tags (``ur-PK``) where the packaged spec writes bare
    language tags (``ur``). A second list in the tree would have to be migrated
    in step with the spec and would silently disagree with it in the meantime,
    so there is none. Changing a tag is a one-file change in
    ``specs/locales.json``; code reaches locales through :func:`locales`,
    :func:`get_locale`, :func:`resolve_direction` and :func:`plural_categories`.

SPEC DISCOVERY AND ITS LIMIT (honest statement)
    The spec is found by walking up from this file until a ``specs/locales.json``
    exists, or from ``RETRACE_LOCALES_SPEC`` when that variable is set. That
    works for a source checkout and for an editable install. It does NOT work
    for a wheel installed without the repository, because ``specs/`` is not
    packaged - :func:`spec_path` raises :class:`SpecNotFoundError` there rather
    than falling back to a built-in list, because a built-in list is exactly the
    duplicate this module exists to avoid. Packaging the spec as package data is
    owed and not done.

``review_status`` is carried through verbatim. ``beta`` means NO human
linguistic review has happened, which RX-30 requires before a locale may be
called complete; this module never upgrades that value.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CLDR_PLURAL_CATEGORIES",
    "DIRECTIONS",
    "Locale",
    "LocaleRegistry",
    "RegistrySpecError",
    "SpecNotFoundError",
    "UnknownLocaleError",
    "get_locale",
    "is_rtl",
    "load_registry",
    "locale_codes",
    "locales",
    "plural_categories",
    "registry",
    "resolve_direction",
    "source_locale",
    "spec_path",
]

#: Set from the CLDR plural-rules syntax. A spec naming anything outside this set
#: is a spec error, not something to accommodate.
CLDR_PLURAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"zero", "one", "two", "few", "many", "other"}
)

DIRECTIONS: Final[frozenset[str]] = frozenset({"ltr", "rtl"})

_SPEC_RELATIVE: Final[str] = "specs/locales.json"
_SPEC_ENV_VAR: Final[str] = "RETRACE_LOCALES_SPEC"


class SpecNotFoundError(RuntimeError):
    """``specs/locales.json`` could not be located (RX-26)."""


class RegistrySpecError(ValueError):
    """The locale spec is present but structurally invalid (RX-26)."""


class UnknownLocaleError(KeyError):
    """A code that the registry does not contain was looked up (RX-26)."""

    def __init__(self, code: str, known: Sequence[str]) -> None:
        self.code = code
        super().__init__(
            f"unknown locale {code!r}; the registry declares {len(known)} locales. "
            "Add it to specs/locales.json - never to calling code."
        )


@dataclass(frozen=True, slots=True)
class Locale:
    """One locale exactly as ``specs/locales.json`` declares it (RX-26).

    ``reviewer`` and ``reviewed_at`` are ``None`` for every locale today. A
    non-null reviewer is the only thing that lifts ``beta`` (RX-30).
    """

    code: str
    name: str
    endonym: str
    script: str
    direction: str
    plural_categories: tuple[str, ...]
    review_status: str
    reviewer: str | None
    reviewed_at: str | None

    @property
    def is_rtl(self) -> bool:
        """Whether this locale lays out right-to-left (RX-28)."""
        return self.direction == "rtl"

    @property
    def is_reviewed(self) -> bool:
        """Whether a human linguistic review record exists (RX-30).

        Requires BOTH a reviewer and a review timestamp. ``review_status`` alone
        is a label; a locale is reviewed only when it names who reviewed it and
        when.
        """
        return self.reviewer is not None and self.reviewed_at is not None

    @property
    def language_subtag(self) -> str:
        """The primary language subtag, lowercased (RX-27).

        Plural and direction families are properties of the language, so a tag
        change from ``ur`` to ``ur-PK`` must not change behaviour. Both reduce
        to ``ur`` here.
        """
        return self.code.replace("_", "-").split("-", 1)[0].lower()


@dataclass(frozen=True, slots=True)
class LocaleRegistry:
    """An immutable, validated view of the locale spec (RX-26)."""

    source_locale: str
    entries: tuple[Locale, ...]
    spec_path: Path | None = None

    @classmethod
    def from_spec(cls, data: Mapping[str, Any], *, path: Path | None = None) -> LocaleRegistry:
        """Validate and build a registry from parsed spec JSON (RX-26).

        Refused, each with a named reason: a missing or empty ``locales`` list; a
        ``count`` that disagrees with the list length (a dropped locale must not
        pass silently); a duplicate code; a direction outside
        :data:`DIRECTIONS`; an empty or non-CLDR plural category set; a
        ``source_locale`` that is not in the list.
        """
        raw = data.get("locales")
        if not isinstance(raw, list) or not raw:
            raise RegistrySpecError("spec has no non-empty 'locales' list")

        declared_count = data.get("count")
        if isinstance(declared_count, int) and declared_count != len(raw):
            raise RegistrySpecError(
                f"spec declares count={declared_count} but lists {len(raw)} locales; "
                "a dropped or added locale must not pass silently"
            )

        entries: list[Locale] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise RegistrySpecError(f"locales[{index}] is not an object")
            code = item.get("code")
            if not isinstance(code, str) or not code.strip():
                raise RegistrySpecError(f"locales[{index}] has no usable 'code'")
            if code in seen:
                raise RegistrySpecError(f"duplicate locale code {code!r}")
            seen.add(code)

            direction = item.get("direction")
            if direction not in DIRECTIONS:
                raise RegistrySpecError(
                    f"locale {code!r} has direction {direction!r}; expected one of "
                    f"{sorted(DIRECTIONS)}"
                )

            categories = item.get("plural_categories")
            if not isinstance(categories, list) or not categories:
                raise RegistrySpecError(f"locale {code!r} declares no plural categories")
            unknown = [c for c in categories if c not in CLDR_PLURAL_CATEGORIES]
            if unknown:
                raise RegistrySpecError(
                    f"locale {code!r} declares non-CLDR plural categories {unknown}"
                )

            entries.append(
                Locale(
                    code=code,
                    name=str(item.get("name", code)),
                    endonym=str(item.get("endonym", item.get("name", code))),
                    script=str(item.get("script", "")),
                    direction=direction,
                    plural_categories=tuple(categories),
                    review_status=str(item.get("review_status", "beta")),
                    reviewer=item.get("reviewer"),
                    reviewed_at=item.get("reviewed_at"),
                )
            )

        source = data.get("source_locale")
        if not isinstance(source, str) or source not in seen:
            raise RegistrySpecError(f"source_locale {source!r} is not one of the declared locales")

        return cls(source_locale=source, entries=tuple(entries), spec_path=path)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Locale]:
        return iter(self.entries)

    def __contains__(self, code: object) -> bool:
        return any(entry.code == code for entry in self.entries)

    @property
    def codes(self) -> tuple[str, ...]:
        """Every declared locale code, in spec order (RX-26)."""
        return tuple(entry.code for entry in self.entries)

    def get(self, code: str) -> Locale:
        """Return the locale for ``code``, or raise :class:`UnknownLocaleError`.

        Matching is exact on the declared tag, then case-insensitive, then on the
        primary language subtag - so ``ur-PK`` still resolves while the tag
        scheme is being reconciled, without any caller hardcoding either spelling.
        """
        for entry in self.entries:
            if entry.code == code:
                return entry
        folded = code.replace("_", "-").lower()
        for entry in self.entries:
            if entry.code.lower() == folded:
                return entry
        subtag = folded.split("-", 1)[0]
        for entry in self.entries:
            if entry.language_subtag == subtag:
                return entry
        raise UnknownLocaleError(code, self.codes)

    @property
    def source(self) -> Locale:
        """The source locale entry (RX-26)."""
        return self.get(self.source_locale)

    @property
    def rtl_codes(self) -> tuple[str, ...]:
        """Codes laid out right-to-left (RX-28)."""
        return tuple(entry.code for entry in self.entries if entry.is_rtl)

    @property
    def reviewed_codes(self) -> tuple[str, ...]:
        """Codes with a real human linguistic review record (RX-30)."""
        return tuple(entry.code for entry in self.entries if entry.is_reviewed)


def spec_path() -> Path:
    """Locate ``specs/locales.json`` (RX-26).

    Raises
    ------
    SpecNotFoundError:
        When no spec is reachable. Deliberately not softened into a built-in
        locale list: see the module docstring.
    """
    override = os.environ.get(_SPEC_ENV_VAR)
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise SpecNotFoundError(f"{_SPEC_ENV_VAR}={override!r} is not a file")
        return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _SPEC_RELATIVE
        if candidate.is_file():
            return candidate
    raise SpecNotFoundError(
        f"no {_SPEC_RELATIVE} found above {here}; set {_SPEC_ENV_VAR} to point at it"
    )


@lru_cache(maxsize=4)
def load_registry(path: str | None = None) -> LocaleRegistry:
    """Load and validate the locale spec once per path (RX-26).

    The result is immutable and cached, so the spec is read from disk once per
    process regardless of how many units ask for it.
    """
    resolved = Path(path) if path is not None else spec_path()
    with resolved.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise RegistrySpecError(f"{resolved} does not contain a JSON object")
    return LocaleRegistry.from_spec(data, path=resolved)


def registry() -> LocaleRegistry:
    """The default registry, loaded from the located spec (RX-26)."""
    return load_registry()


def locales(*, source: LocaleRegistry | None = None) -> tuple[Locale, ...]:
    """Every declared locale, in spec order (RX-26)."""
    return (source or registry()).entries


def locale_codes(*, source: LocaleRegistry | None = None) -> tuple[str, ...]:
    """Every declared locale code, in spec order (RX-26)."""
    return (source or registry()).codes


def get_locale(code: str, *, source: LocaleRegistry | None = None) -> Locale:
    """Return one locale by code (RX-26)."""
    return (source or registry()).get(code)


def resolve_direction(code: str, *, source: LocaleRegistry | None = None) -> str:
    """Return ``"ltr"`` or ``"rtl"`` for ``code`` (RX-28)."""
    return get_locale(code, source=source).direction


def plural_categories(code: str, *, source: LocaleRegistry | None = None) -> tuple[str, ...]:
    """Return the CLDR plural categories the spec declares for ``code`` (RX-27)."""
    return get_locale(code, source=source).plural_categories


def is_rtl(code: str, *, source: LocaleRegistry | None = None) -> bool:
    """Whether ``code`` is laid out right-to-left (RX-28)."""
    return get_locale(code, source=source).is_rtl


def source_locale(*, source: LocaleRegistry | None = None) -> str:
    """The code of the source locale every catalogue is measured against (RX-26)."""
    return (source or registry()).source_locale
