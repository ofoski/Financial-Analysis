"""Second step of the split pipeline, run after split_detection.py flags a
period whose diluted share count changed between filings. That flag alone
isn't proof of a real split, it could also be a filer tagging error (see
RGTI's 2023-03-31 case, where 124,778 was mistakenly filed instead of
124,778,000). To confirm it, this module searches the company's 8-K
filings in the date window between the original and restated filing for
one that actually announces a split, then asks an LLM to pull the real
ratio and dates out of that filing's text, extraction only, not judgment,
since by this point we already know from XBRL that something real changed.
"""
import json
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Research research@example.com"}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"

EXTRACTION_PROMPT = """Extract stock split information from this 8-K excerpt. Respond ONLY with JSON, nothing else.

Rules:
- "split_ratio" should be written as "X-for-Y" (e.g. "3-for-1" means 3 new shares issued for every 1 old share held).
- "split_type" should be "forward" (more shares after split) or "reverse" (fewer shares after split).
- "effective_date" is when the split takes effect for shareholders, NOT the record date, NOT the filing date, NOT the trading date.
- "record_date" is the date used to determine which shareholders are eligible - this is different from effective_date, do not confuse them.
- If a field isn't stated in the text, use null. Do not guess or infer a date/ratio that isn't explicitly written.
- "source_sentence" should be the exact sentence you extracted the ratio and dates from.

Text:
{text}

Output JSON in this exact schema:
{{"split_ratio": string or null, "split_type": "forward" or "reverse" or null, "effective_date": string or null, "record_date": string or null, "distribution_date": string or null, "source_sentence": string or null}}"""


def _parse_8k_block(block, results):
    """accession (accession number) is SEC's unique ID for one specific
    filing, e.g. "0001596532-26-000174". No two filings ever share one.

    1. block holds parallel lists of a company's real filings: form,
       accessionNumber, filingDate, primaryDocument.
    2. zip(...) walks them together, one filing at a time. Example:
       form="8-K", accession="0001596532-26-000174", filed="2026-08-04",
       primary_doc="anet-20260804.htm".
    3. Keep only filings where form == "8-K".
    4. Append (accession with dashes removed, filed, primary_doc) to
       results, the same list the caller passed in."""
    for form, accession, filed, primary_doc in zip(
        block.get("form", []), block.get("accessionNumber", []),
        block.get("filingDate", []), block.get("primaryDocument", []),
    ):
        if form == "8-K":
            results.append((accession.replace("-", ""), filed, primary_doc))


def get_8k_filings(cik):
    """1. Pad cik and fetch SEC's submissions page for this company.
    2. filings = resp.json()["filings"] has two parts: "recent" (real
       filing data, ready to use) and "files" (pointers to extra pages
       holding older filings that didn't fit in "recent").

    3. results = [], collects every real 8-K found, from both sources.

    4. _parse_8k_block(filings["recent"], results) checks "recent"
       first, adding any 8-Ks it finds into results.

    5. For each file_entry in filings["files"] (e.g.
       {"name": "CIK0001327567-submissions-001.json", ...}), since this
       is older data, it's fetched with a different URL: not
       SUBMISSIONS_URL, but "https://data.sec.gov/submissions/" +
       file_entry["name"], e.g.
       "https://data.sec.gov/submissions/CIK0001327567-submissions-001.json".
       Then _parse_8k_block(r.json(), results) checks that page the same
       way, adding any 8-Ks it finds into the same results list.
       
    6. Return results, e.g.
       [("000119312526361122", "2026-08-21", "d180372d8k.htm"),
        ("000132756719000014", "2019-05-29", "panw-8xkxq319earningsrelea.htm")].
       The second one only exists because step 5 checked the older page
       too; it would be missing if the code only ever checked "recent"."""
    
    cik_padded = str(cik).zfill(10)
    resp = requests.get(SUBMISSIONS_URL.format(cik_padded), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    filings = resp.json().get("filings", {})

    results = []
    _parse_8k_block(filings.get("recent", {}), results)

    for file_entry in filings.get("files", []):
        r = requests.get("https://data.sec.gov/submissions/" + file_entry["name"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        _parse_8k_block(r.json(), results)

    return results


def _clean_html(raw_html):
    """Strips HTML down to plain text. Example:
    '<p>Revenue <b>up</b> 10%&nbsp;this&nbsp;quarter.</p>' becomes
    'Revenue up 10% this quarter.'"""
    raw = re.sub(r"<script.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub("<[^<]+?>", " ", raw)
    clean = re.sub(r"&\w+;", " ", clean)
    clean = re.sub(r"&#\d+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def fetch_8k_text(cik_int, accession, primary_doc):
    """Downloads one real document and returns its plain text. Example:
    fetch_8k_text(1596532, "000159653221000351", "anet-20211101.htm")
    fetches https://www.sec.gov/Archives/edgar/data/1596532/000159653221000351/anet-20211101.htm."""
    
    url = f"{ARCHIVES_BASE}/{cik_int}/{accession}/{primary_doc}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return _clean_html(resp.text)


def _ex99_documents(cik_int, accession):
    """Returns this filing's EX-99.x exhibit filenames (its press
    releases), the ones worth checking for a split announcement.

    1. Build this filing's real index page URL and fetch/parse it into
       soup, e.g. for ANET's accession 000159653221000351, the URL is
       https://www.sec.gov/Archives/edgar/data/1596532/000159653221000351/0001596532-21-000351-index.htm.

    2. soup.find_all("tr") returns every table row on that page, e.g. its
       EX-99.1 row: <tr><td>2</td><td>EX-99.1</td>
       <td><a href="/Archives/.../ex991q321-earningsrelease.htm">ex991q321-earningsrelease.htm</a></td>
       <td>EX-99.1</td><td>250871</td></tr>.

    3. row.find_all("td") gets that row's own cells, e.g. cells =
       [<td>2</td>, <td>EX-99.1</td>, <td><a>...</a></td>, <td>EX-99.1</td>, <td>250871</td>].

    4. Every real document row has 5 cells; only the header row is
       different, since it uses <th> instead of <td>, giving cells = [].
       Skip any row under 4 cells so the header row doesn't crash cells[3]
       below.

    5. cells[3] is the "Type" column (e.g. "8-K", "EX-99.1",
       "EX-101.SCH"), skip this row unless it starts with "EX-99" (e.g.
       cells[3].get_text(strip=True) == "EX-99.1" here, so this row is kept).

    6. cells[2] is the "Document" column, find its <a> link tag and read
       the real address out of its href attribute (e.g.
       "/Archives/edgar/data/1596532/000159653221000351/ex991q321-earningsrelease.htm").

    7. Keep just the filename at the end of that address (split("/")[-1])
       and append it to docs (e.g. "ex991q321-earningsrelease.htm")."""

    dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    url = f"{ARCHIVES_BASE}/{cik_int}/{accession}/{dashed}-index.htm"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    docs = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        if not cells[3].get_text(strip=True).startswith("EX-99"):
            continue
        link = cells[2].find("a")
        if link and link.get("href"):
            docs.append(link["href"].split("/")[-1])
    return docs


def find_candidate_8ks(cik_int, start_date, end_date):
    """Among this company's 8-Ks filed strictly between start_date and
    end_date, returns the ones whose text actually mentions "split".

    1. candidates = [], collects every real match found.

    2. get_8k_filings returns every 8-K this company has ever filed, as a
       list of (accession, filed, primary_doc) tuples, e.g.
       ("000...123", "2023-05-10", "company-20230510.htm"). This loop
       goes through them one at a time.

    3. Three dates matter here: start_date is the end date of the
       quarter before the share-count jump; end_date is the date the
       report that revealed the jumped value was itself filed; filed is
       this one specific 8-K's own filing date, the one being checked.
       Skip this 8-K if filed isn't between start_date and end_date, and
       skip it if it has no primary_doc at all.

    4. docs = [primary_doc], starts with just this filing's main document
       (e.g. docs = ["company-20230510.htm"]).

    5. Add this filing's EX-99.x exhibits (from _ex99_documents) onto
       docs too, e.g. docs becomes ["company-20230510.htm",
       "ex991-pressrelease.htm"], so both the main document and its
       exhibits get checked.

    6. Go through every doc in docs (not stopping at the first match),
       download each one's plain text with fetch_8k_text, and append this
       filing's info ({"accession": "000...123", "filed": "2023-05-10",
       "primary_doc": doc, "text": ...}) to candidates for each document
       whose text mentions "split". A single filing can produce more than
       one entry this way, e.g. if both the main document and
       "ex991-pressrelease.htm" mention "split", since a real ratio can
       be sitting in either one and a real split shouldn't be missed just
       because the wrong document was checked first.

    7. Return candidates, one entry per matching document (a filing with
       several matching documents can appear more than once)."""
    
    candidates = []
    for accession, filed, primary_doc in get_8k_filings(cik_int):
        if not (start_date < filed < end_date):
            continue
        if not primary_doc:
            continue

        docs = [primary_doc]
        try:
            docs += [d for d in _ex99_documents(cik_int, accession) if d != primary_doc]
        except Exception:  # noqa: BLE001, S110
            pass

        for doc in docs:
            try:
                text = fetch_8k_text(cik_int, accession, doc)
            except Exception:  # noqa: BLE001, S112
                continue
            if "split" in text.lower():
                candidates.append({"accession": accession, "filed": filed, "primary_doc": doc, "text": text})
    return candidates


def extract_split_details(text, window=6000):
    """Runs the LLM extraction prompt on one document's text, trimmed to
    the section around the word "split" so the model isn't given the
    whole document. This step only pulls out fields (ratio, dates), it
    does not decide whether a split is real, since we already know from
    the earlier "split" search that this document mentions one.

    1. Find where "split" first appears in text, then back up 1000
       characters from there (or start from 0 if it's not found).
    2. Cut out a window-sized slice (default 6000 characters) of text
       starting there, so the LLM gets relevant context instead of the
       whole document.
    3. Fill that slice into the extraction prompt template and send it
       to the local Ollama model, asking for a JSON reply.
    4. Parse the model's reply as JSON and return it, e.g.
       {"split_ratio": "2-for-1", "split_type": "forward", ...}, or
       return an error dict if the reply isn't valid JSON."""
    text_lower = text.lower()
    pos = text_lower.find("split")
    start = max(0, pos - 1000) if pos != -1 else 0
    section = text[start:start + window]

    prompt = EXTRACTION_PROMPT.format(text=section)
    resp = requests.post(OLLAMA_CHAT_URL, json={
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 300},
        "format": "json",
    }, timeout=120)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "failed_to_parse", "raw": content}


def parse_split_ratio(split_ratio_str):
    """Turns "3-for-1" into 3.0, "1-for-10" into 0.1, matching the same
    direction as the XBRL ratio (restated/original): a forward split
    increases the share count, so X-for-Y means the count multiplies by
    X/Y. Returns None if it isn't in the expected format.

    The regex is written to be flexible since this string comes from an
    LLM, not a fixed format, so it needs to understand a couple of
    variations on the same ratio, e.g. "2-for-1", "2 for 1", and
    "2for1" should all still parse to the same 2.0.
    """
    if not split_ratio_str:
        return None
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*-?\s*for\s*-?\s*(\d+(?:\.\d+)?)", split_ratio_str, re.IGNORECASE)
    if not match:
        return None
    x, y = float(match.group(1)), float(match.group(2))
    if y == 0:
        return None
    return x / y


def confirm_split(cik_int, xbrl_change, ratio_tolerance=0.15, invert_llm_ratio=False):
    """xbrl_change is one dict from split_detection.detect_splits, e.g.
    {"ticker": "ANET", "ratio": 3.995, "search_start": "2021-09-30",
    "next_filed": "2022-02-15", ...}, a single suspicious share-count
    jump found purely from SEC's raw numbers, not yet backed by any real
    filing. This function tries to find that real evidence.

    1. Work out the real date window to search in, using xbrl_change's
       own search_start and next_filed. If either is missing, stop here
       and return "unconfirmed", there's nothing to search with.
    2. Search that window for real 8-Ks (and their EX-99 exhibits)
       mentioning "split". If none are found, return "unconfirmed" too,
       no evidence exists either way.
    3. For each one found, ask the LLM to read out its stated ratio, and
       compare that to xbrl_change's own ratio (e.g. the LLM reads
       "4-for-1" = 4.0, xbrl_change's ratio is 3.995, close enough to
       count as a match).
    4. Once one of a filing's documents gives a matching ratio, skip
       checking that same filing's other documents (e.g. its EX-99
       exhibit), it's already confirmed, no need to spend another LLM
       call on it. This only skips documents within the same filing
       (same accession); a different filing in the window, even from
       the same company, still gets checked normally. If a document's
       ratio doesn't match, its filing's other documents still get
       checked too, since a real match might be elsewhere.
    5. Return xbrl_change plus a "confirmation" key: "confirmed" if any
       document's ratio matched, "ratio_mismatch" if documents were
       found but none matched."""
    
    start_date = xbrl_change.get("search_start") or xbrl_change.get("prev_filed")
    end_date = xbrl_change.get("next_filed")
    if not start_date or not end_date:
        return {**xbrl_change, "confirmation": {"status": "unconfirmed", "reason": "missing filing dates"}}

    candidates = find_candidate_8ks(cik_int, start_date, end_date)
    if not candidates:
        return {**xbrl_change, "confirmation": {"status": "unconfirmed", "reason": "no 8-K mentioning split in window"}}

    xbrl_ratio = xbrl_change.get("ratio")
    details = []
    any_match = False
    resolved_accessions = set()
    for c in candidates:
        if c["accession"] in resolved_accessions:
            continue

        extracted = extract_split_details(c["text"])
        llm_ratio = parse_split_ratio(extracted.get("split_ratio"))
        if invert_llm_ratio and llm_ratio:
            llm_ratio = 1 / llm_ratio
        matches = (
            llm_ratio is not None and xbrl_ratio is not None
            and abs(llm_ratio - xbrl_ratio) / xbrl_ratio < ratio_tolerance
        )
        if matches:
            any_match = True
            resolved_accessions.add(c["accession"])
        details.append({"accession": c["accession"], "filed": c["filed"], "llm_ratio": llm_ratio, "ratio_matches_xbrl": matches, **extracted})

    status = "confirmed" if any_match else "ratio_mismatch"
    return {**xbrl_change, "confirmation": {"status": status, "details": details}}
