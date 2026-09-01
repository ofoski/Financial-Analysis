"""Guided extraction: instead of pulling company, variables, and
period out of one long free-written question, the app asks for each
one separately and reads each short, direct reply on its own.

The conversation moves through three steps, driven by advance():
1. Company - extract_company_reply reads the reply and copies out the
   company name or ticker, which resolve_company then resolves to a
   real (ticker, entry) pair.
2. Period - extract_period_reply reads the reply and pulls out a year
   and, if mentioned, a quarter (Q1-Q4 or FY for a full year); no
   quarter mentioned defaults to FY.
3. Variables - extract_variables_reply reads the reply and returns
   which of the 9 tracked variables were mentioned.

advance() re-asks the same step if a reply couldn't be resolved, and
moves to the next step once it can. Company extraction, and the
fallback path for variables when a reply isn't a clean list, go
through the fine-tuned model. Year, quarter, and a clean list of
variable names are resolved with plain text matching instead, no
model call needed.
"""
import difflib

from resolver import (
    VARIABLES,
    _generate_json_from_messages,
    _generate_text,
    display_name,
    resolve_company,
)


def extract_company_reply(answer):
    """Reads a short, direct reply to "which company", returns the
    company reference (not yet resolved to a real ticker)."""
    prompt = (
        f'The user was asked "Which company would you like to ask about?" and replied: "{answer}"\n\n'
        "Copy just the company name or ticker from their reply, word-for-word.\n\n"
        'Return exactly this JSON shape, nothing else: {"company": "<copied word-for-word>"}'
    )
    raw = _generate_json_from_messages([{"role": "user", "content": prompt}], r"\{.*?\}", max_new_tokens=40)
    return raw.get("company") if raw else None


_QUARTER_KEYWORDS = [
    (["q1", "first quarter"], "Q1"),
    (["q2", "second quarter"], "Q2"),
    (["q3", "third quarter"], "Q3"),
    (["q4", "fourth quarter"], "Q4"),
    (["fy", "annual", "fiscal", "full year"], "FY"),
]


def _extract_year(answer):
    """Plain, deterministic year lookup: a standalone 4-digit number in
    the reply - no model involved. Real testing found the model itself
    gets this wrong for specific years for no clear reason (it read
    "2025" as no year at all, while "2023", "2024", and "2026" all
    worked fine), so this doesn't rely on it for something this
    simple."""
    for word in answer.replace(",", " ").split():
        word = word.strip(".!?")
        if word.isdigit() and len(word) == 4 and 1990 <= int(word) <= 2100:
            return int(word)
    return None


def _extract_quarter(answer):
    """Plain, deterministic quarter lookup: the possible wordings are a
    small, fixed set (Q1-Q4, "first quarter".."fourth quarter", or
    "annual"/"fiscal"/"full year"/"FY" for a full year), so this
    doesn't need the model either - real testing found it unreliable
    here too, it failed to recognize "annual", "fiscal", and "full
    year" as meaning FY even when asked in isolation."""
    text = answer.lower()
    for keywords, quarter in _QUARTER_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return quarter
    return None


def extract_period_reply(answer):
    """Reads a short, direct reply to "which year and quarter", returns
    {"year": ... or None, "quarter": ... or None}. Both are pulled out
    with plain text matching, no model call at all - the set of valid
    years and quarter phrasings is small and well defined, and real
    testing found the model unreliable on parts of it (a specific
    year, and several of the full-year wordings)."""
    return {"year": _extract_year(answer), "quarter": _extract_quarter(answer)}


def _split_reply(answer):
    """Breaks a reply into individual phrases on commas, semicolons,
    "&", and "and" - the plain ways people separate items in a list."""
    text = answer.replace(" and ", ",").replace(";", ",").replace("&", ",")
    return [p.strip() for p in text.split(",") if p.strip()]


def _match_variables_deterministic(answer):
    """Splits the reply into phrases and fuzzy-matches each one
    directly against the 9 variable names (the same difflib approach
    already used to match a typed company name to a real one) - no
    model involved. Returns (matched, leftover) - leftover is any
    phrase that didn't closely resemble one of the 9, meaning this
    reply isn't a clean list and needs the model's help instead.

    A phrase only counts as a match if it's also close in length to
    the variable name - real testing found an unrelated word like
    "casher" scores as a close match to "Cash" on character similarity
    alone (it starts with the same 4 letters), even more closely than
    a genuine typo like "Cach" does, so length is checked too."""
    display_names = [display_name(v) for v in VARIABLES]
    matched = []
    leftover = []
    for part in _split_reply(answer):
        close = difflib.get_close_matches(part, display_names, n=3, cutoff=0.6)
        variable = None
        for name in close:
            if abs(len(part) - len(name)) <= 1:
                variable = VARIABLES[display_names.index(name)]
                break
        if variable:
            if variable not in matched:
                matched.append(variable)
        else:
            leftover.append(part)
    return matched, leftover


def _match_variables_with_model(answer):
    """Falls back to the model for a reply that isn't a clean list -
    a full sentence, extra punctuation, filler words. Rather than
    asking it to judge yes/no on all 9 (unreliable - real testing
    showed it loses track past a couple of variables) or write a full
    JSON list (real testing showed it can slip back into inventing
    XBRL tag names instead), this only asks it to copy out which of
    the 9 names it recognizes in the text, then the same fuzzy-match
    used above resolves those copied names back to the real variable
    list. If the model finds nothing, this returns an empty list, same
    as a plain non-match."""
    display_names = [display_name(v) for v in VARIABLES]
    prompt = (
        f"Here are 9 tracked financial variables: {', '.join(display_names)}.\n\n"
        f'Text: "{answer}"\n\n'
        "Which of the 9 variables above are mentioned in that text? Ignore unrelated words.\n\n"
        "Rules: only use the exact names from the list of 9 above, copied word-for-word - never "
        "invent a different name, spelling, or abbreviation. List each one at most once. If none "
        'are mentioned, output "none".\n\n'
        "Output as a plain comma-separated list, nothing else."
    )
    raw = _generate_text(prompt)
    if raw.lower() == "none":
        return []
    matched, _ = _match_variables_deterministic(raw)
    return matched


def extract_variables_reply(answer):
    """Reads a short, direct reply to "which variables", returns a
    plain list of matched variable names. Tries plain text matching
    first - splitting the reply into a list and comparing each piece
    directly to the 9 known names - since that's fast, free, and
    real testing showed it's 100% accurate whenever someone answers
    with a clean list, which covers the vast majority of real replies.
    Only falls back to the model for whatever plain matching couldn't
    resolve (a full sentence, filler words, odd punctuation), and even
    then only asks it to copy out variable names it recognizes, not to
    judge or generate anything new."""
    matched, leftover = _match_variables_deterministic(answer)
    if not leftover:
        return matched

    for variable in _match_variables_with_model(answer):
        if variable not in matched:
            matched.append(variable)
    return matched


def new_state():
    return {"step": "company", "ticker": None, "entry": None, "year": None, "quarter": None, "variables": None}


def advance(state, message):
    """Given the current guided-conversation state and the user's
    latest reply, moves the conversation forward one step. Returns
    (state, prompt_for_user) - prompt_for_user is either the next
    question to ask, a re-ask if this step's answer wasn't usable, or
    None once all three steps are done and state is ready for the real
    fetch/match pipeline."""
    if state["step"] == "company":
        company = extract_company_reply(message)
        resolved = resolve_company(company) if company else None
        if not resolved:
            return state, f"I couldn't find a real company matching \"{company or message}\". Could you give the company name or ticker again?"
        ticker, entry = resolved
        state["ticker"], state["entry"] = ticker, entry
        state["step"] = "period"
        return state, f"Got it, {entry['name']} ({ticker}). Which year and quarter would you like? (e.g. \"2024\" or \"Q1 2025\")"

    if state["step"] == "period":
        period = extract_period_reply(message)
        if not period.get("year"):
            return state, "I need a year to look this up, which year would you like?"
        state["year"] = period["year"]
        state["quarter"] = period.get("quarter") or "FY"
        state["step"] = "variables"
        variables_list = ", ".join(display_name(v) for v in VARIABLES)
        return state, f"Which variable(s) would you like? Choose from: {variables_list}"

    if state["step"] == "variables":
        variables = extract_variables_reply(message)
        if not variables:
            return state, "I couldn't match that to any of the 9 tracked variables, could you name them again?"
        state["variables"] = variables
        state["step"] = "done"
        return state, None

    return state, None
