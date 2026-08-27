"""Records the full candidate list and which one got picked for every
real variable match, so a sample can be manually checked against the
real filing each week. Called as one extra step after a match completes,
not from inside the matching logic itself, so it stays easy to remove or
change without touching how matching actually works.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent / "match_log.jsonl"


def _already_logged(ticker, period_end, variable, candidates, selected):
    """True if a line with this exact ticker/period_end/variable/
    candidates/selected already exists - skips re-logging the same real
    result (e.g. from re-running the same query), while still logging a
    genuinely different outcome (different candidates, or a different
    pick) as its own new entry."""
    if not LOG_PATH.exists():
        return False
    with open(LOG_PATH) as f:
        for line in f:
            entry = json.loads(line)
            if (entry["ticker"], entry["period_end"], entry["variable"], entry["candidates"], entry["selected"]) == \
               (ticker, period_end, variable, candidates, selected):
                return True
    return False


def log_match(ticker, period_end, variable, candidates, selected, value):
    """Appends one JSON line: {id, timestamp, ticker, period_end,
    variable, candidates, selected, value}. candidates is the full list
    of (label, value) pairs the model had to choose from; selected is
    the label(s) it picked (or None); value is the resolved number.
    Skips writing if this exact result was already logged before.

    Real example line: {"id": "...", "timestamp": "2026-08-26T...",
    "ticker": "AAPL", "period_end": "2025-06-28", "variable": "Revenue",
    "candidates": [["Revenues", 94036000000.0], ...], "selected":
    "Revenues", "value": 94036.0}."""
    candidates = [list(c) for c in candidates]
    if _already_logged(ticker, period_end, variable, candidates, selected):
        return

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "period_end": period_end,
        "variable": variable,
        "candidates": candidates,
        "selected": selected,
        "value": value,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
