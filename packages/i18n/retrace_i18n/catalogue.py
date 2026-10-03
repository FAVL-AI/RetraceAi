"""Message catalogues and resolution (RX-26, RX-29, RX-30).

ONE CATALOGUE PER LOCALE, at ``packages/i18n/catalogues/<code>.json``. The
English file is the SOURCE: structural coverage of every other locale is
measured against its key set, and nothing is "complete" that does not cover it.

THE RESOLUTION RULE THAT MATTERS
    A missing key and an untranslated key both fall back to the source string,
    because showing nothing is worse. The fallback is NEVER silent: the
    :class:`Resolution` carries flags, and ``flags`` is what the interface must
    render as a truthfulness chip (docs/UX.md, RX-25). A caller that reads
    ``.value`` and ignores ``.flags`` reintroduces the exact defect RX-30 names -
    an unreviewed or absent translation presented as if it were a reviewed one -
    so :meth:`Translator.text` returns the flags alongside the text and
    :meth:`Translator.resolve` is the only way to get at a value.

    Separately, a MISSING KEY is a build defect rather than a translation state:
    :meth:`Translator.missing_keys` enumerates it for the coverage report and
    ``strict=True`` raises. "Pending" is an expected, honest state; "missing" is
    not.

ENTRY SHAPES
    A singular entry has ``value`` (a string, or ``null`` when pending). A plural
    entry has ``forms``, a mapping from CLDR plural category to string, and is
    complete only when every category the locale DECLARES is present and
    non-null (RX-27).

    Every non-English entry carries ``machine_generated: true`` and a ``status``
    of ``"translated"`` or ``"pending"``. ``null`` plus ``"pending"`` is the
    honest answer where confidence is absent; a plausible-looking wrong string
    is a defect a reviewer cannot see, so it is never written.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from .formats import NumberFormat
from .plurals import select_plural
from .protected import placeholders, validate
from .registry import Locale, LocaleRegistry, get_locale, registry, source_locale

__all__ = [
    "CATALOGUE_DIRNAME",
    "Catalogue",
    "CatalogueError",
    "Entry",
    "FLAG_BETA",
    "FLAG_FALLBACK",
    "FLAG_MACHINE_TRANSLATED",
    "FLAG_MISSING_KEY",
    "FLAG_PENDING",
    "MissingKeyError",
    "Resolution",
    "STATUS_PENDING",
    "STATUS_SOURCE",
    "STATUS_TRANSLATED",
    "Translator",
    "catalogue_dir",
    "load_catalogue",
    "load_catalogues",
]

CATALOGUE_DIRNAME: Final[str] = "catalogues"

STATUS_SOURCE: Final[str] = "source"
STATUS_TRANSLATED: Final[str] = "translated"
STATUS_PENDING: Final[str] = "pending"

#: Flags are rendered as truthfulness chips. The two lowercase values are the
#: literal tokens docs/UX.md mandates and must not be restyled away (RX-25, RX-30).
FLAG_MISSING_KEY: Final[str] = "missing-key"
FLAG_PENDING: Final[str] = "pending"
FLAG_FALLBACK: Final[str] = "fallback-to-source"
FLAG_MACHINE_TRANSLATED: Final[str] = "machine-translated"
FLAG_BETA: Final[str] = "beta"


class CatalogueError(ValueError):
    """A catalogue file is structurally invalid (RX-26)."""


class MissingKeyError(KeyError):
    """A key absent from the source catalogue, or absent under ``strict`` (RX-26)."""

    def __init__(self, key: str, code: str) -> None:
        self.key = key
        self.code = code
        super().__init__(f"key {key!r} is not present in catalogue {code!r}")


@dataclass(frozen=True, slots=True)
class Entry:
    """One message in one locale (RX-26, RX-30)."""

    key: str
    value: str | None = None
    forms: Mapping[str, str | None] | None = None
    description: str = ""
    machine_generated: bool = False
    status: str = STATUS_PENDING

    @property
    def is_plural(self) -> bool:
        """Whether this entry carries per-category forms (RX-27)."""
        return self.forms is not None

    @property
    def is_pending(self) -> bool:
        """Whether this entry has no usable string at all (RX-30)."""
        if self.is_plural:
            forms = self.forms or {}
            return not any(isinstance(v, str) and v for v in forms.values())
        return not (isinstance(self.value, str) and self.value)

    def declared_forms_complete(self, categories: Iterable[str]) -> bool:
        """Whether every category the locale declares has a non-null form (RX-27)."""
        forms = self.forms or {}
        return all(isinstance(forms.get(c), str) and forms.get(c) for c in categories)

    def strings(self) -> tuple[str, ...]:
        """Every non-null string this entry holds (RX-29 scanning)."""
        if self.is_plural:
            return tuple(v for v in (self.forms or {}).values() if isinstance(v, str))
        return (self.value,) if isinstance(self.value, str) else ()

    @classmethod
    def from_mapping(cls, key: str, data: Mapping[str, Any]) -> Entry:
        """Parse one catalogue entry, validating its protected spans (RX-26, RX-29)."""
        forms_raw = data.get("forms")
        forms: Mapping[str, str | None] | None = None
        if forms_raw is not None:
            if not isinstance(forms_raw, Mapping):
                raise CatalogueError(f"{key}: 'forms' must be an object")
            forms = {str(k): (v if v is None else str(v)) for k, v in forms_raw.items()}
        value = data.get("value")
        if value is not None and not isinstance(value, str):
            raise CatalogueError(f"{key}: 'value' must be a string or null")
        if value is None and forms is None and "value" not in data and "forms" not in data:
            raise CatalogueError(f"{key}: entry declares neither 'value' nor 'forms'")
        entry = cls(
            key=key,
            value=value,
            forms=forms,
            description=str(data.get("description", "")),
            machine_generated=bool(data.get("machine_generated", False)),
            status=str(data.get("status", STATUS_PENDING)),
        )
        for text in entry.strings():
            validate(text, field=key)
        return entry


@dataclass(frozen=True, slots=True)
class Catalogue:
    """Every message for one locale, plus its review record (RX-26, RX-30)."""

    code: str
    review_status: str
    reviewer: str | None
    reviewed_at: str | None
    entries: Mapping[str, Entry]
    number_format: NumberFormat | None = None
    path: Path | None = None
    notes: str = ""

    @property
    def is_reviewed(self) -> bool:
        """Whether a human linguistic review record exists (RX-30).

        Needs a reviewer AND a timestamp. ``review_status`` is a label, not
        evidence; a catalogue claiming ``reviewed`` with ``reviewer: null`` is
        not reviewed and is reported as unreviewed.
        """
        return self.reviewer is not None and self.reviewed_at is not None

    @property
    def keys(self) -> frozenset[str]:
        """Every key present in this catalogue (RX-26)."""
        return frozenset(self.entries)

    def pending_keys(self) -> tuple[str, ...]:
        """Keys present but with no usable string - the honest nulls (RX-30)."""
        return tuple(sorted(k for k, e in self.entries.items() if e.is_pending))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, path: Path | None = None) -> Catalogue:
        """Parse a catalogue document (RX-26)."""
        code = data.get("locale")
        if not isinstance(code, str) or not code:
            raise CatalogueError(f"{path or '<memory>'}: no 'locale' code")
        messages = data.get("messages")
        if not isinstance(messages, Mapping) or not messages:
            raise CatalogueError(f"{code}: 'messages' must be a non-empty object")
        entries = {
            str(key): Entry.from_mapping(str(key), value)
            for key, value in messages.items()
            if isinstance(value, Mapping)
        }
        if len(entries) != len(messages):
            raise CatalogueError(f"{code}: every message must be an object")
        formats = data.get("formats")
        number_format: NumberFormat | None = None
        if isinstance(formats, Mapping) and isinstance(formats.get("number"), Mapping):
            number_format = NumberFormat.from_mapping(formats["number"], code=code)
        return cls(
            code=code,
            review_status=str(data.get("review_status", "beta")),
            reviewer=data.get("reviewer"),
            reviewed_at=data.get("reviewed_at"),
            entries=entries,
            number_format=number_format,
            path=path,
            notes=str(data.get("notes", "")),
        )


def catalogue_dir() -> Path:
    """Directory holding ``<code>.json`` catalogues (RX-26)."""
    return Path(__file__).resolve().parents[1] / CATALOGUE_DIRNAME


@lru_cache(maxsize=64)
def load_catalogue(code: str, directory: str | None = None) -> Catalogue:
    """Load and validate one catalogue, cached per code (RX-26)."""
    base = Path(directory) if directory else catalogue_dir()
    path = base / f"{code}.json"
    if not path.is_file():
        raise CatalogueError(f"no catalogue file for locale {code!r} at {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise CatalogueError(f"{path} does not contain a JSON object")
    catalogue = Catalogue.from_mapping(data, path=path)
    if catalogue.code != code:
        raise CatalogueError(f"{path} declares locale {catalogue.code!r}, expected {code!r}")
    return catalogue


def load_catalogues(
    *,
    source: LocaleRegistry | None = None,
    directory: str | None = None,
) -> dict[str, Catalogue]:
    """Load every catalogue the registry declares (RX-26).

    Raises if one is absent: a locale in the spec with no catalogue is a missing
    deliverable, not an empty one, and must not be reported as 0% coverage of
    something that exists.
    """
    reg = source or registry()
    return {code: load_catalogue(code, directory) for code in reg.codes}


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome of looking up one key in one locale (RX-26, RX-30).

    ``flags`` is not decoration. An interface that renders ``value`` without
    rendering ``flags`` is presenting machine output as reviewed output.
    """

    key: str
    requested_locale: str
    used_locale: str
    value: str
    flags: tuple[str, ...] = ()
    category: str | None = None
    entry: Entry | None = field(default=None, repr=False)

    @property
    def is_missing_key(self) -> bool:
        """Whether the key was absent from the requested catalogue (RX-26)."""
        return FLAG_MISSING_KEY in self.flags

    @property
    def is_pending(self) -> bool:
        """Whether the locale has no translation for this key yet (RX-30)."""
        return FLAG_PENDING in self.flags

    @property
    def is_source_fallback(self) -> bool:
        """Whether the shown text came from the source locale (RX-26)."""
        return FLAG_FALLBACK in self.flags

    def format(self, **params: object) -> str:
        """Substitute ``{name}`` placeholders, refusing unknown ones (RX-26)."""
        needed = placeholders(self.value)
        missing = needed - set(params)
        if missing:
            raise KeyError(
                f"{self.key}: missing placeholder values {sorted(missing)} for locale "
                f"{self.used_locale!r}"
            )
        out = self.value
        for name in needed:
            out = out.replace("{" + name + "}", str(params[name]))
        return out


class Translator:
    """Resolves keys for one locale against the source catalogue (RX-26, RX-30)."""

    def __init__(
        self,
        code: str,
        *,
        catalogue: Catalogue | None = None,
        source_catalogue: Catalogue | None = None,
        registry_source: LocaleRegistry | None = None,
        directory: str | None = None,
    ) -> None:
        self._registry = registry_source or registry()
        self.locale: Locale = get_locale(code, source=self._registry)
        self.source_code = source_locale(source=self._registry)
        self.catalogue = catalogue or load_catalogue(self.locale.code, directory)
        if source_catalogue is not None:
            self.source = source_catalogue
        elif self.locale.code == self.source_code:
            self.source = self.catalogue
        else:
            self.source = load_catalogue(self.source_code, directory)

    @property
    def is_source(self) -> bool:
        """Whether this translator is the source locale itself (RX-26)."""
        return self.locale.code == self.source_code

    def _base_flags(self) -> list[str]:
        if self.is_source:
            return []
        flags = [FLAG_MACHINE_TRANSLATED]
        if not self.catalogue.is_reviewed:
            flags.append(FLAG_BETA)
        return flags

    def missing_keys(self) -> tuple[str, ...]:
        """Source keys absent from this catalogue - a build defect (RX-26)."""
        return tuple(sorted(self.source.keys - self.catalogue.keys))

    def extra_keys(self) -> tuple[str, ...]:
        """Keys present here but not in the source - also a defect (RX-26)."""
        return tuple(sorted(self.catalogue.keys - self.source.keys))

    def pending_keys(self) -> tuple[str, ...]:
        """Keys awaiting a translation, honestly declared as null (RX-30)."""
        out: list[str] = []
        for key in sorted(self.source.keys & self.catalogue.keys):
            entry = self.catalogue.entries[key]
            if entry.is_pending:
                out.append(key)
            elif entry.is_plural and not entry.declared_forms_complete(
                self.locale.plural_categories
            ):
                out.append(key)
        return tuple(out)

    def resolve(self, key: str, *, count: object = None, strict: bool = False) -> Resolution:
        """Resolve ``key``, flagging every fallback (RX-26, RX-27, RX-30).

        Raises
        ------
        MissingKeyError:
            If ``key`` is not in the SOURCE catalogue at all (always), or if it
            is absent from this locale's catalogue and ``strict`` is set.
        """
        if key not in self.source.entries:
            raise MissingKeyError(key, self.source.code)
        flags = self._base_flags()
        source_entry = self.source.entries[key]
        entry = self.catalogue.entries.get(key)

        if entry is None:
            if strict:
                raise MissingKeyError(key, self.catalogue.code)
            flags.extend((FLAG_MISSING_KEY, FLAG_FALLBACK))
            value, category = self._render(source_entry, count, self.source_code)
            return Resolution(
                key=key,
                requested_locale=self.locale.code,
                used_locale=self.source_code,
                value=value,
                flags=tuple(dict.fromkeys(flags)),
                category=category,
                entry=source_entry,
            )

        if entry.status == STATUS_PENDING or entry.is_pending:
            flags.extend((FLAG_PENDING, FLAG_FALLBACK))
            value, category = self._render(source_entry, count, self.source_code)
            return Resolution(
                key=key,
                requested_locale=self.locale.code,
                used_locale=self.source_code,
                value=value,
                flags=tuple(dict.fromkeys(flags)),
                category=category,
                entry=entry,
            )

        try:
            value, category = self._render(entry, count, self.locale.code)
        except MissingKeyError:
            # A plural entry whose selected category is absent: fall back to the
            # source form for that category and say so, rather than show a
            # grammatically wrong form or an empty string.
            flags.extend((FLAG_PENDING, FLAG_FALLBACK))
            value, category = self._render(source_entry, count, self.source_code)
            return Resolution(
                key=key,
                requested_locale=self.locale.code,
                used_locale=self.source_code,
                value=value,
                flags=tuple(dict.fromkeys(flags)),
                category=category,
                entry=entry,
            )
        return Resolution(
            key=key,
            requested_locale=self.locale.code,
            used_locale=self.locale.code,
            value=value,
            flags=tuple(dict.fromkeys(flags)),
            category=category,
            entry=entry,
        )

    def _render(self, entry: Entry, count: object, code: str) -> tuple[str, str | None]:
        if not entry.is_plural:
            if not isinstance(entry.value, str):
                raise MissingKeyError(entry.key, code)
            return entry.value, None
        if count is None:
            raise ValueError(f"{entry.key} is a plural message and needs a count")
        if not isinstance(count, int | float | str):
            raise TypeError(f"{entry.key}: count must be a number, not {type(count).__name__}")
        category = select_plural(code, count, source=self._registry)
        form = (entry.forms or {}).get(category)
        if not isinstance(form, str) or not form:
            raise MissingKeyError(f"{entry.key}#{category}", code)
        return form, category

    def text(self, key: str, **params: object) -> tuple[str, tuple[str, ...]]:
        """Return ``(text, flags)`` for a singular message (RX-26, RX-30).

        Returns the flags WITH the text deliberately: there is no API here that
        hands back a bare string, because a bare string is how an unreviewed
        machine translation gets rendered as if it were reviewed.
        """
        resolution = self.resolve(key)
        return resolution.format(**params), resolution.flags

    def plural(self, key: str, count: int | float | str, **params: object) -> tuple[
        str, tuple[str, ...]
    ]:
        """Return ``(text, flags)`` for a plural message (RX-27, RX-30)."""
        resolution = self.resolve(key, count=count)
        merged: dict[str, object] = {"n": count, **params}
        return resolution.format(**merged), resolution.flags
