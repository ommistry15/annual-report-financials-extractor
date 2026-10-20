#!/usr/bin/env python3
"""
Annual Report Financials Extractor
==================================

For every annual-report PDF in a folder, saves two PDFs:

    CFS    Consolidated Balance Sheet, Statement of Profit and Loss and
           Cash Flow Statement (the Statement of Changes in Equity is left out)
    CFSN   Notes to the Consolidated Financial Statements

Files are named <Company>_<FY>_CFS.pdf and <Company>_<FY>_CFSN.pdf, with the
company and year read from the report itself.

Most people should use the window (double-click "Extract Financials.bat").
Command line, mainly for testing:
    python ar_extract.py "C:\\...\\Annual_Reports"
    python ar_extract.py "C:\\...\\Annual_Reports" --dry-run
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

try:
    import pypdfium2 as pdfium
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("Missing libraries. Install them with:\n    pip install pypdf pypdfium2")

SECTIONS = {
    "cfs": "Consolidated Financial Statements",
    "cfsn": "Notes to Consolidated Financial Statements",
}
FILE_TAG = {"cfs": "CFS", "cfsn": "CFSN"}
OUT_DIR_NAME = "Extracted"

HEADING_ZONE = 0.35      # top share of the page searched for headings
MAX_HEADING_WORDS = 16   # a heading line is short; body text is not


# ---------------------------------------------------------------- text utils

def norm(s):
    s = s.lower().replace("\u2019", "").replace("'", "").replace("`", "")
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\-\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Page:
    index: int
    full: str            # normalized text of the whole page
    head_lines: list     # normalized lines in the heading zone
    all_lines: list      # normalized lines of the whole page
    has_text: bool


def read_pages(path):
    pdf = pdfium.PdfDocument(path)
    pages = []
    for i in range(len(pdf)):
        page = pdf[i]
        tp = page.get_textpage()
        raw = tp.get_text_range() or ""
        w, h = page.get_size()
        if page.get_rotation() in (90, 270):
            head_raw = raw  # rotated landscape page: "top" is unreliable
        else:
            head_raw = tp.get_text_bounded(0, h * (1 - HEADING_ZONE), w, h) or ""
        split = lambda t: [norm(l) for l in re.split(r"[\r\n]+", t) if norm(l)]
        pages.append(Page(i, norm(raw), split(head_raw), split(raw),
                          len(raw.strip()) > 30))
        tp.close()
        page.close()
    pdf.close()
    return pages


# ---------------------------------------------------------- pattern matching

STATEMENT_TITLES = {
    "bs": r"balance sheet",
    "pl": r"(statement of profit and loss|profit and loss (account|statement)"
          r"|statement of (comprehensive )?income|income statement)",
    "soce": r"statement of changes in (equity|shareholders equity)",
    "cf": r"(statement of cash ?flows?|cash ?flows? statement)",
}
P = {
    "auditor": r"auditors? report",
    "notes": r"(notes|schedules?) (to|forming part of|to and forming part of|on|annexed to)"
             r"( the)?( ind as)? (consolidated |standalone )?(ind as )?(financial statements?|accounts)",
    "mda": r"^management(s)? discussion and analysis",
    "directors": r"^(boards|directors) report",
    "cg": r"^(report on )?corporate governance( report)?$",
    "brsr": r"^business responsibility( and sustainability)? report",
    "aoc1": r"form (no )?aoc ?- ?1|salient features of (the )?financial statements? of subsidiar",
    "notice": r"^notice( of (the )?\d*\w* annual general meeting)?$|^notice is hereby given",
    "proxy": r"^(proxy form|attendance slip|route map)",
}
# Text that only appears in an auditor's report, never on a statement page
AUDIT_TEXT = (r"we have audited|key audit matters?|basis for opinion|in conjunction with our audit"
              r"|our responsibility is to express|auditors responsibilit")
DATED = r"as at|as on|year ended|period ended|for the year|consolidated|standalone|contd|continued|\bcont\b"


def heading_hit(lines, pattern, max_words=MAX_HEADING_WORDS):
    """Return the first short line matching pattern (joined with the lines
    after it, which usually carry the date), else None."""
    rx = re.compile(pattern)
    for k, ln in enumerate(lines):
        nxt = lines[k + 1] if k + 1 < len(lines) else ""
        after = lines[k + 2] if k + 2 < len(lines) else ""
        if len(ln.split()) > max_words:
            continue
        if rx.search(ln):
            return f"{ln} | {nxt} | {after}"
        # titles often wrap: "statement of cash" / "flows"
        if nxt and len(nxt.split()) <= 4 and rx.search(ln + " " + nxt):
            return f"{ln} {nxt} | {after}"
    return None


def heading(page, pattern, max_words=MAX_HEADING_WORDS):
    hit = heading_hit(page.head_lines, pattern, max_words)
    if hit is None and not page.head_lines:
        hit = heading_hit(page.all_lines[:15], pattern, max_words)
    return hit


def page_basis(title, page):
    """'consolidated' or 'standalone' for a statement title on a page."""
    if "consolidated" in title:
        return "consolidated"
    if "standalone" in title:
        return "standalone"
    # Title without the word; look at the rest of the page's heading area
    head = " ".join(page.head_lines[:8])
    return "consolidated" if "consolidated" in head and "standalone" not in head else "standalone"


def number_share(page):
    """Share of words that are numbers: about 0.3-0.6 on a statement page,
    under 0.05 on prose such as an auditor's report or accounting policies."""
    words = page.full.split()
    return sum(bool(re.fullmatch(r"[\d\-]+", w)) for w in words) / max(len(words), 1)


def statement_kind(page, basis):
    """Which primary statement this page is titled as (bs/pl/soce/cf), else None.
    The title must start its line, so sentences such as "...the consolidated
    balance sheet..." in an auditor's report do not count."""
    if re.search(AUDIT_TEXT, page.full) or number_share(page) < 0.15:
        return None
    for kind, pat in STATEMENT_TITLES.items():
        hit = heading(page, rf"^(the )?((consolidated|standalone) )?(ind as )?{pat}\b")
        if (hit and re.search(DATED, hit) and page_basis(hit, page) == basis
                and not re.search(P["notes"], hit)):
            return kind
    return None


def content_kind(page):
    """Classify a statement page by its wording, for pages whose title was
    not found (continuation pages, sideways pages, titles drawn as images)."""
    f = page.full
    cf = re.search(r"(operating|investing|financing) activities", f)
    bs = "total assets" in f or "equity and liabilities" in f
    pl = re.search(r"revenue from operations|total income|profit before tax|total expenses", f)
    soce = "changes in equity" in f or (
        "retained earnings" in f and re.search(r"balance (as at|at the)", f))
    if soce and not (cf or bs or pl):
        return "soce"
    if cf:
        return "cf"
    if bs:
        return "bs"
    if pl:
        return "pl"
    return "soce" if soce else None


NOT_A_HEADING = r"accompanying|integral part|refer|read with|in terms of|see "
NOTES_OPENING = (r"^((material|significant) accounting policies|(1 )?corporate information"
                 r"|(1 )?(general information|company overview|group information|background and operations))")


def is_notes_heading(page, basis, opening=False):
    """Notes title page. With opening=True also accept the first-note
    headings ("Material accounting policies", "1 Corporate information")
    that some reports use instead of a "Notes to..." title."""
    lines = page.head_lines or page.all_lines[:15]
    other = "standalone" if basis == "consolidated" else "consolidated"
    if any(len(ln.split()) <= MAX_HEADING_WORDS and re.search(P["notes"], ln)
           and other not in ln and not re.search(NOT_A_HEADING, ln)
           for ln in lines):
        return True
    return opening and any(re.search(NOTES_OPENING, ln) for ln in lines[:6])


def is_toc(page):
    keys = [P["auditor"], "management discussion", "directors report", "corporate governance",
            "business responsibility", "notice"]
    hits = sum(1 for k in keys if re.search(k, page.full))
    numbered = sum(1 for ln in page.all_lines if re.search(r"\b\d{1,3}$", ln))
    return hits >= 3 and (page.index < 12 or numbered >= 8)


AUDIT_OPENING = r"report on the audit of (the )?(consolidated |standalone )?(ind as )?financial statements"


def is_auditor_first_page(page):
    to_members = re.search(r"to the (members|shareholders|board of directors)", page.full)
    line = heading(page, P["auditor"])
    if line and "annexure" not in line:
        return bool(to_members)
    # some reports print the title as artwork; the text starts at "To the Members"
    return bool(to_members and heading(page, AUDIT_OPENING))


# ----------------------------------------------------------------- detection

@dataclass
class Result:
    pages: dict = field(default_factory=dict)    # section -> list of 0-based page indexes
    basis: str = "consolidated"
    warnings: list = field(default_factory=list)
    company: str = ""    # e.g. "Premier_Energies"
    fy: str = ""         # e.g. "FY2026"
    n_pages: int = 0


def find_statement_cluster(pages, basis):
    """Locate the block of primary statements (BS/PL/SOCE/CF) for a basis."""
    hits = [(p.index, statement_kind(p, basis)) for p in pages if not is_toc(p)]
    hits = [(i, k) for i, k in hits if k]
    clusters, cur = [], []
    for i, k in hits:
        if cur and i - cur[-1][0] > 3:
            clusters.append(cur)
            cur = []
        cur.append((i, k))
    if cur:
        clusters.append(cur)

    def score(cl):
        kinds = {k for _, k in cl}
        end = cl[-1][0]
        # real statements carry a "Note" column and are followed by notes
        note_col = sum(1 for i, _ in cl if re.search(r"\bnotes?\b|\bschedule\b", pages[i].full))
        notes_after = any(is_notes_heading(pages[j], basis, opening=True)
                          for j in range(end + 1, min(end + 5, len(pages))))
        return notes_after * 5 + min(note_col, 3) + len(kinds)

    clusters = [c for c in clusters if len({k for _, k in c}) >= 2]
    if not clusters:
        return None
    best = max(clusters, key=score)
    return best[0][0], best[-1][0]


def detect_financials(pages, basis, res):
    cl = find_statement_cluster(pages, basis)
    if not cl:
        return False
    fs_start, last_stmt = cl
    n = len(pages)

    # A balance sheet whose title wasn't readable can sit just before the block
    while (fs_start > 0 and content_kind(pages[fs_start - 1]) == "bs"
           and not re.search(AUDIT_TEXT, pages[fs_start - 1].full)
           and not is_notes_heading(pages[fs_start - 1], basis)):
        fs_start -= 1

    # Notes start: first notes-heading page after the statements
    notes_start = None
    for j in range(fs_start + 1, min(last_stmt + 6, n)):
        if is_notes_heading(pages[j], basis, opening=True) and not statement_kind(pages[j], basis):
            notes_start = j
            break
    if notes_start is None:
        notes_start = last_stmt + 1
        res.warnings.append("notes heading not found; assumed notes start after last statement")

    # Keep Balance Sheet, P&L and Cash Flow pages; leave out Changes in Equity
    keep, prev = [], None
    for j in range(fs_start, notes_start):
        kind = statement_kind(pages[j], basis) or content_kind(pages[j]) or prev
        if kind != "soce":
            keep.append(j)
        prev = kind
    res.pages["cfs"] = keep

    # Notes end: next page whose title clearly starts something else
    other = "standalone" if basis == "consolidated" else "consolidated"
    notes_end = n - 1
    for j in range(notes_start + 1, n):
        p = pages[j]
        if is_toc(p):
            continue
        top = p.head_lines[:6] or p.all_lines[:6]
        stop = (is_auditor_first_page(p)
                or statement_kind(p, other)
                or any(re.search(P["notes"], ln) and other in ln and len(ln.split()) <= MAX_HEADING_WORDS
                       for ln in top)
                or any(heading_hit(top, P[k], 12) for k in
                       ("aoc1", "notice", "proxy", "mda", "directors", "brsr", "cg")))
        if stop:
            notes_end = j - 1
            break
    if notes_end == n - 1:
        res.warnings.append("notes run to end of file; check the last pages")
    res.pages["cfsn"] = list(range(notes_start, notes_end + 1))
    return True


def detect_company(pages):
    names = {}
    for p in pages:
        for m in re.finditer(r"to the (?:members|shareholders) of ([a-z0-9 \-]{3,60}?) (?:limited|ltd)\b", p.full):
            names[m.group(1)] = names.get(m.group(1), 0) + 1
    if not names:
        return ""
    best = max(names, key=names.get)
    return "_".join(w.upper() if len(w) <= 3 and w not in ("and", "the", "of") else w.capitalize()
                    for w in best.split())


def detect_fy(pages, res):
    """Year of the statements, read from headings like 'As at March 31, 2026'."""
    years = {}
    scope = res.pages.get("cfs") or range(len(pages))
    for i in scope:
        for ln in pages[i].head_lines[:12]:
            if re.search(r"as at|as on|year ended|period ended", ln):
                for y in re.findall(r"\b((?:19|20)\d{2})\b", ln)[:1]:
                    years[y] = years.get(y, 0) + 1
    return f"FY{max(years, key=years.get)}" if years else ""


def fy_from_name(name):
    """'Voltas_AR_2023.pdf' -> FY2023, 'AR25.pdf' -> FY2025, 'AR_2022-23' -> FY2023."""
    m = re.findall(r"(?:19|20)\d{2}", name)
    if m:
        m2 = re.search(r"((?:19|20)\d{2})\s*[-_]\s*(\d{2})(?!\d)", name)
        return f"FY{m2.group(1)[:2]}{m2.group(2)}" if m2 else f"FY{m[-1]}"
    m = re.findall(r"(?<!\d)(\d{2})(?!\d)", name)
    return f"FY20{m[-1]}" if m else ""


def detect(path):
    """Find the consolidated statements and notes in one report. Falls back
    to standalone when the company has no consolidated statements."""
    pages = read_pages(path)
    res = Result(n_pages=len(pages))
    if not any(p.has_text for p in pages):
        res.warnings.append("no text in this PDF (scanned?) - it needs OCR first")
        res.fy = fy_from_name(os.path.basename(path))
        return res
    if sum(p.has_text for p in pages) < 0.5 * len(pages):
        res.warnings.append("many pages have no text; results may be incomplete")
    if not detect_financials(pages, "consolidated", res):
        if detect_financials(pages, "standalone", res):
            res.basis = "standalone"
            res.warnings.append("no consolidated statements in this report; standalone saved instead")
    res.company = detect_company(pages)
    res.fy = detect_fy(pages, res) or fy_from_name(os.path.basename(path))
    for s in SECTIONS:
        if not res.pages.get(s):
            res.warnings.append(f"{FILE_TAG[s]} not found")
    return res


# ------------------------------------------------------------------- output

def fmt_pages(idx):
    """[82, 83, 85, 86] -> '83-84, 86-87' (1-based, as shown in a PDF viewer)."""
    if not idx:
        return ""
    runs, start, prev = [], idx[0], idx[0]
    for i in list(idx[1:]) + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        runs.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        if i is not None:
            start = prev = i
    return ", ".join(runs)


def parse_pages(text, n):
    """'83-84, 86-87' -> [82, 83, 85, 86]. Raises ValueError on bad input."""
    out = []
    for part in re.split(r"[,;]", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:(?:-|to)\s*(\d+))?", part)
        if not m:
            raise ValueError(f"'{part}' is not a page range (use e.g. 45-78)")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if not (1 <= a <= b <= n):
            raise ValueError(f"'{part}' is outside pages 1-{n}")
        out.extend(range(a - 1, b))
    return out


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*\s]+', "_", s).strip("_.")


def base_name(res, path, fallback_company=""):
    """'Voltas_FY2025' (or the file name if company and year are unknown)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return safe_name("_".join(x for x in (res.company or fallback_company, res.fy) if x) or stem)


def output_path(out_dir, base, section, basis):
    suffix = "_STANDALONE" if basis == "standalone" else ""
    return os.path.join(out_dir, f"{base}_{FILE_TAG[section]}{suffix}.pdf")


def write_pdf(src_path, page_idx, dest):
    reader = PdfReader(src_path)
    w = PdfWriter()
    for i in page_idx:
        w.add_page(reader.pages[i])
    with open(dest, "wb") as f:
        w.write(f)


def list_reports(folder):
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    return sorted(files, key=lambda f: (fy_from_name(os.path.basename(f)) or "~", f.lower()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract consolidated financial statements and notes.")
    ap.add_argument("folder", help="folder with annual-report PDFs (or a single PDF)")
    ap.add_argument("-o", "--out", help=f"output folder (default: <folder>/{OUT_DIR_NAME})")
    ap.add_argument("--dry-run", action="store_true", help="only detect and print page ranges")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.folder)
    if os.path.isfile(src):
        files, folder = [src], os.path.dirname(src)
    else:
        folder, files = src, list_reports(src)
    if not files:
        sys.exit(f"No PDF files found in {src}")
    out = os.path.abspath(args.out or os.path.join(folder, OUT_DIR_NAME))
    os.makedirs(out, exist_ok=True)

    used = set()
    for path in files:
        print(f"\n{os.path.basename(path)}")
        try:
            res = detect(path)
        except Exception as e:  # damaged / encrypted PDF etc.
            print(f"  ERROR reading file: {e}")
            continue
        base = base_name(res, path)
        if base in used:
            base = safe_name(f"{base}_{os.path.splitext(os.path.basename(path))[0]}")
        used.add(base)
        print(f"  {res.company or '?'} / {res.fy or '?'} ({res.basis})")
        for s in SECTIONS:
            print(f"  {FILE_TAG[s]:<5} pages {fmt_pages(res.pages.get(s)) or 'NOT FOUND'}")
        for w in res.warnings:
            print(f"  ! {w}")
        if args.dry_run:
            continue
        for s in SECTIONS:
            if res.pages.get(s):
                dest = output_path(out, base, s, res.basis)
                write_pdf(path, res.pages[s], dest)
                print(f"  saved {os.path.basename(dest)}")
    print(f"\nDone. Output: {out}")


if __name__ == "__main__":
    main()
