"""Resolves a company name or ticker (as extracted from a user's free
text question) to a real (ticker, entry) pair from SEC's full public
company list, via xbrl_pipeline/edgar_helpers.get_cik_map().

No fuzzy/similarity matching on purpose: character-similarity scoring
against SEC's full ~10,000-company list lets unrelated names through
just because they share letters with some real company (e.g. "banana"
matching a company called "Cannae"). Matching is exact ticker, exact
normalized name, whole-word prefix, whole-word-anywhere, and finally
whole-word-set (order independent) - every tier is an exact word
match, never a score. No hardcoded per-company aliases either: a
company whose legal name shares no words at all with the name it's
commonly known by (e.g. Schlumberger's SEC filer name is now "SLB
Limited") won't resolve by name here - only by ticker, since there's
no general rule that covers an arbitrary rebrand.

Returns one of three outcomes so the caller can ask the user to pick
when the name is ambiguous, rather than silently guessing:
  - resolve_company("AAPL") -> ("single", (ticker, entry))
  - resolve_company("Apple") -> ("multiple", [(ticker, entry), ...])
      if more than one real company's name starts with "Apple"
  - resolve_company("NotARealCompany") -> ("not_found", None)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "xbrl_pipeline"))
from edgar_helpers import get_cik_map

_cik_map = None


def _get_cik_map():
    """Downloads SEC's full ticker -> CIK/name list on first use only,
    then reuses it in memory for the rest of the process's lifetime."""
    global _cik_map  # noqa: PLW0603
    if _cik_map is None:
        _cik_map = get_cik_map()
    return _cik_map


_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|LLC|PLC|GROUP|HOLDINGS?)\b\.?,?",
    re.IGNORECASE,
)


def _normalize_name(name):
    """Strips punctuation, casing, and common legal suffixes (Inc,
    Corp, Ltd, ...), so "Gitlab Inc." and "GITLAB INC" compare equal.
    Apostrophes are dropped outright rather than turned into a space,
    so "McDonald's" becomes "MCDONALDS" (one word), matching how SEC's
    own filer name "MCDONALDS CORP" normalizes. "&" is treated as the
    word "AND" (not dropped), so "Air Products & Chemicals" and "Air
    Products and Chemicals" normalize the same way."""
    name = name.replace("&", " AND ")
    name = _SUFFIXES.sub("", name.upper())
    name = name.replace("'", "")
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    return " ".join(name.split())


def resolve_company(company):
    """Resolves whatever was extracted from the user's question - a
    real ticker (e.g. "AAPL") or a company name (e.g. "Apple") - to
    real SEC company entries.

    Ticker is tried first, since it's an exact, unambiguous lookup.
    Then an exact normalized-name match. Then a whole-word prefix
    match (a short common name like "Apple" is the start of more than
    one real legal name, e.g. "APPLE INC" and "APPLE HOSPITALITY REIT
    INC"). If no prefix match exists, falls back to a whole-word match
    anywhere in the name, since SEC's real filer names don't always put
    the common name first (e.g. "Disney" needs to match "Walt Disney
    Co", where Disney is the second word) - still an exact word match,
    not similarity scoring, just not restricted to the start of the
    name. If more than one company matches, all of them are returned
    so the caller can ask the user to pick the right one by its real
    legal name, instead of silently guessing.
    """
    cik_map = _get_cik_map()

    exact = cik_map.get(company.strip().upper())
    if exact:
        return "single", (company.strip().upper(), exact)

    target = _normalize_name(company)

    normalized_to_ticker = {}
    for ticker, entry in cik_map.items():
        normalized_to_ticker.setdefault(_normalize_name(entry["name"]), ticker)

    if target in normalized_to_ticker:
        ticker = normalized_to_ticker[target]
        return "single", (ticker, cik_map[ticker])

    prefix_matches = [name for name in normalized_to_ticker if name.startswith(target + " ")]
    word_matches = prefix_matches or [
        name for name in normalized_to_ticker
        if f" {target} " in f" {name} "
    ]

    if not word_matches:
        # Last resort: SEC sometimes files under a surname-first order
        # (e.g. "W.R. Berkley Corporation" -> "BERKLEY W R CORP", "J.B.
        # Hunt Transport" -> "HUNT J B TRANSPORT SERVICES INC"). Checks
        # whether every word in the target appears somewhere in the
        # name, regardless of order - still an exact word match, not a
        # similarity score, just not requiring the words to be in the
        # same order or adjacent.
        target_words = set(target.split())
        word_matches = [
            name for name in normalized_to_ticker
            if target_words and target_words.issubset(name.split())
        ]

    if not word_matches and " " not in target and len(target) <= 5:
        # SEC sometimes spaces out short initialisms (e.g. "VF" ->
        # "V F CORP"). Only tried for short, single-word targets, so it
        # can't turn an ordinary word into a false match.
        spaced_target = " ".join(target)
        word_matches = [
            name for name in normalized_to_ticker
            if name.startswith(spaced_target + " ") or f" {spaced_target} " in f" {name} "
        ]

    if not word_matches:
        return "not_found", None

    candidates = [(normalized_to_ticker[name], cik_map[normalized_to_ticker[name]]) for name in word_matches]
    if len(candidates) == 1:
        return "single", candidates[0]

    return "multiple", candidates
