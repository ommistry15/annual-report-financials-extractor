# Annual Report Financials Extractor

Point it at a folder of annual-report PDFs (one company, any number of years). For every report it
saves two PDFs:

| File                    | What's in it                                                        |
|-------------------------|---------------------------------------------------------------------|
| `Voltas_FY2025_CFS.pdf`  | Consolidated Balance Sheet, Statement of Profit and Loss, Cash Flow Statement, then the "Other expenses" note (the split of other expenses) |
| `Voltas_FY2025_CFSN.pdf` | Notes to the Consolidated Financial Statements                      |

The Statement of Changes in Equity is always left out. The company name and year are read from the
report itself, so the PDFs can be named anything.

## First time only
Install Python from python.org and tick **"Add Python to PATH"** during setup.

## Use
1. Double-click **`Extract Financials.bat`**. (The first time, it installs two small components.)
2. Click **Choose folder...** and pick the folder with the annual reports.
3. Tick what you want: **CFS**, **CFSN**, or both. Your choice is remembered for next time.
4. Click **Extract**.

The files are saved in an `Extracted` folder inside your reports folder. **Open results folder**
takes you there.

## If a result looks wrong
Each row shows the pages used, as numbered in your PDF viewer. Orange or red rows need a look.
Select the row and click **Correct pages...** (or double-click it). Type the right pages, e.g.
`190-193`, or `83-84, 86-87` to skip pages in between, and click **Save**. **Open the annual report**
lets you check the page numbers.

## Notes
- If a year has no consolidated statements (company had no subsidiaries), the standalone ones are
  saved instead and the files end in `_STANDALONE`.
- Scanned PDFs with no text can't be read. Run them through OCR first.
- Command line (for testing): `python ar_extract.py "<folder>" --dry-run`
