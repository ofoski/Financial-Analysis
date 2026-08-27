"""Runs when the user clicks app.py's "Check for stock split" button."""
from split_confirmation import confirm_split
from split_detection import detect_splits


def find_splits_since(ticker, cik_int, reference_quarter_end):
    """detect_splits finds share-count ratio jumps from reference_quarter_end
    onward, then confirm_split searches 8-Ks for the word "split" and has
    the LLM confirm the real ratio between those two quarters."""
    candidates = detect_splits(ticker, cik_int, since=reference_quarter_end)

    splits_found = []
    for candidate in candidates:
        confirmed = confirm_split(cik_int, candidate)
        if confirmed["confirmation"]["status"] != "confirmed":
            continue
        for detail in confirmed["confirmation"]["details"]:
            if detail.get("ratio_matches_xbrl"):
                splits_found.append({"ratio": candidate["ratio"], "split_ratio_label": detail.get("split_ratio"),
                                      "effective_date": detail.get("effective_date")})
                break

    return splits_found

