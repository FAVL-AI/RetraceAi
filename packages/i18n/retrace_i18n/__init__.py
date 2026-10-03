"""``retrace_i18n`` - localisation for RETRACE AI (RX-26 .. RX-31).

Public surface, grouped by the requirement it serves:

REGISTRY (RX-26)
    :func:`locales`, :func:`locale_codes`, :func:`get_locale`,
    :func:`resolve_direction`, :func:`plural_categories`, :func:`registry`.
    ``specs/locales.json`` is the only locale list; nothing here duplicates it.

CATALOGUES (RX-26, RX-30)
    :class:`Translator`, :class:`Resolution`, :func:`load_catalogue`.
    Every lookup returns its truthfulness flags with its text - there is no API
    that hands back a bare string, because a bare string is how an unreviewed
    machine translation gets presented as a reviewed one.

PLURALS (RX-27)
    :func:`select_plural`. The CLDR rules here are an ASSUMPTION written from
    knowledge of the cardinal rules, not read from a pinned CLDR release; see
    :mod:`retrace_i18n.plurals` for the verification that is owed.

DIRECTION AND BIDI (RX-28)
    :func:`resolve_direction`, :func:`render_message`, :func:`strip_isolates`.
    Four locales are RTL: ar, he, fa and ur. Urdu is RTL in the registry even
    though the upstream prose omitted it - a recorded deviation.

PROTECTED SPANS (RX-29)
    :func:`protect`, :func:`unprotect`, :func:`protected_spans`,
    :func:`translate_preserving`. Quotations, identifiers, DOIs, units, dataset
    names and digests are marked in the message value and survive a translation
    pass byte-identically.

COVERAGE (RX-26, RX-30)
    :func:`build_report`, :func:`write_report`. Reviewed coverage is 0 of 36 and
    no locale is complete, because no human linguistic review has happened.
"""

from __future__ import annotations

from .bidi import LRI, PDI, isolate, render_for_direction, render_message, strip_isolates
from .catalogue import (
    FLAG_BETA,
    FLAG_FALLBACK,
    FLAG_MACHINE_TRANSLATED,
    FLAG_MISSING_KEY,
    FLAG_PENDING,
    Catalogue,
    CatalogueError,
    Entry,
    MissingKeyError,
    Resolution,
    Translator,
    catalogue_dir,
    load_catalogue,
    load_catalogues,
)
from .coverage import build_report, report_path, write_report
from .formats import FormatUnavailable, NumberFormat, format_integer
from .labels import (
    OUTCOME_MESSAGE_KEYS,
    TRUTHFULNESS_MESSAGE_KEYS,
    TRUTHFULNESS_TOKENS,
    outcome_label_violations,
)
from .plurals import (
    Operands,
    PluralCategoryMismatch,
    UnsupportedPluralLocale,
    compute_plural_category,
    plural_rule_name,
    select_plural,
)
from .protected import (
    CLOSE,
    OPEN,
    ProtectedSpanError,
    placeholders,
    protect,
    protected_spans,
    segments,
    span_violations,
    translate_preserving,
    unprotect,
)
from .registry import (
    Locale,
    LocaleRegistry,
    RegistrySpecError,
    SpecNotFoundError,
    UnknownLocaleError,
    get_locale,
    is_rtl,
    load_registry,
    locale_codes,
    locales,
    plural_categories,
    registry,
    resolve_direction,
    source_locale,
    spec_path,
)

__all__ = [
    "CLOSE",
    "FLAG_BETA",
    "FLAG_FALLBACK",
    "FLAG_MACHINE_TRANSLATED",
    "FLAG_MISSING_KEY",
    "FLAG_PENDING",
    "LRI",
    "OPEN",
    "OUTCOME_MESSAGE_KEYS",
    "PDI",
    "TRUTHFULNESS_MESSAGE_KEYS",
    "TRUTHFULNESS_TOKENS",
    "Catalogue",
    "CatalogueError",
    "Entry",
    "FormatUnavailable",
    "Locale",
    "LocaleRegistry",
    "MissingKeyError",
    "NumberFormat",
    "Operands",
    "PluralCategoryMismatch",
    "ProtectedSpanError",
    "RegistrySpecError",
    "Resolution",
    "SpecNotFoundError",
    "Translator",
    "UnknownLocaleError",
    "UnsupportedPluralLocale",
    "build_report",
    "catalogue_dir",
    "compute_plural_category",
    "format_integer",
    "get_locale",
    "is_rtl",
    "isolate",
    "load_catalogue",
    "load_catalogues",
    "load_registry",
    "locale_codes",
    "locales",
    "outcome_label_violations",
    "placeholders",
    "plural_categories",
    "plural_rule_name",
    "protect",
    "protected_spans",
    "registry",
    "render_for_direction",
    "render_message",
    "report_path",
    "resolve_direction",
    "segments",
    "select_plural",
    "source_locale",
    "span_violations",
    "spec_path",
    "strip_isolates",
    "translate_preserving",
    "unprotect",
    "write_report",
]
