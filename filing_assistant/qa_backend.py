"""Shared backend for all the UI variants: runs extract.py ->
resolver.py -> pipeline.py for one question and returns plain text.
Kept separate from any particular UI so different front-end layouts
(chat-log style, card style, ...) can all call the same logic.
"""
import threading
import time

import extract
import pipeline
from resolver import resolve_company

QUARTER_LABELS = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}

WORD = "Processing"


def format_value(value, variable):
    if value is None:
        return "N/A"
    if variable == "EPS Diluted":
        return f"${value:,.2f}"
    return f"${value:,.0f}"


def answer(message):
    extracted = extract.extract(message)
    extract.unload_model()  # free the 7B extractor's VRAM before the adapter loads

    if extracted is None:
        return "Sorry, I couldn't understand that question. Could you rephrase it?"

    company = extracted.get("company")
    period_type = extracted.get("period_type")
    year = extracted.get("year")
    quarter_num = extracted.get("quarter")
    variables = extracted.get("variables") or []

    if not company or not year or not variables:
        return "I couldn't find a company, year, and financial variable in that question. Could you be more specific?"

    status, data = resolve_company(company)

    if status == "not_found":
        return f"I couldn't find a real company matching '{company}'."

    if status == "multiple":
        names = "\n".join(f"{entry['name']} ({ticker})" for ticker, entry in data[:10])
        return (
            f"More than one real company matches '{company}':\n\n{names}\n\n"
            "Please ask again naming the one you meant, or its ticker."
        )

    ticker, entry = data
    quarter = "FY" if period_type == "annual" else QUARTER_LABELS.get(quarter_num, "FY")
    period_label = str(year) if quarter == "FY" else f"{quarter} {year}"

    results = pipeline.match_variables(ticker, entry["cik"], variables, str(year), quarter)

    lines = [f"{entry['name']} ({ticker}), {period_label}", ""]
    lines += pipeline.result_lines(results, format_value)

    return "\n".join(lines)


def stream_answer(message):
    """Runs answer() in a background thread and yields a typing-style
    "Processing" animation (built up letter by letter, then cycling
    dots) while it works, followed by the final answer. Any exception
    in the worker is caught so the UI always ends on a real message
    instead of hanging forever on the animation."""
    result = {}

    def worker():
        try:
            result["text"] = answer(message)
        except Exception as e:  # noqa: BLE001
            result["text"] = f"Something went wrong answering that: {e}"

    thread = threading.Thread(target=worker)
    thread.start()

    for i in range(1, len(WORD) + 1):
        if not thread.is_alive():
            break
        yield WORD[:i]
        time.sleep(0.06)

    dots = 0
    while thread.is_alive():
        dots = (dots % 3) + 1
        yield WORD + "." * dots
        time.sleep(0.5)

    thread.join()
    yield result.get("text", "Something went wrong answering that.")
