"""
Window for the Annual Report Financials Extractor.

Pick a folder of annual-report PDFs, click Extract, and every report gets
<Company>_<FY>_CFS.pdf and <Company>_<FY>_CFSN.pdf in an "Extracted" folder
next to the reports. Start it by double-clicking "Extract Financials.bat".
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ar_extract as ax  # noqa: E402

APP_TITLE = "Annual Report Financials Extractor"
SETTINGS = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "ARFinancialsExtractor", "settings.json")


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def open_path(path):
    try:
        os.startfile(path)
    except (AttributeError, OSError):
        messagebox.showinfo(APP_TITLE, path)


class App:
    def __init__(self, root):
        self.root = root
        self.rows = {}           # tree item id -> dict(path, res, base, out_dir, files)
        self.msgs = queue.Queue()
        self.busy = False

        root.title(APP_TITLE)
        root.geometry("980x680")
        root.minsize(760, 520)
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 6))
        style.configure("Treeview", rowheight=26)

        main = ttk.Frame(root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, style="Hint.TLabel",
                  text="Saves the Consolidated Financial Statements (Balance Sheet, Profit & Loss, "
                       "Cash Flow, Other expenses) and their Notes from every annual report in a folder."
                  ).pack(anchor="w", pady=(2, 12))

        # Step 1: folder
        step1 = ttk.LabelFrame(main, text=" 1.  Folder with the annual report PDFs ", padding=10)
        step1.pack(fill="x")
        settings = load_settings()
        self.folder = tk.StringVar(value=settings.get("folder", ""))
        ttk.Entry(step1, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(step1, text="Choose folder...", command=self.choose).pack(side="left", padx=(8, 0))

        # Step 2: what to extract
        step2 = ttk.LabelFrame(main, text=" 2.  What to extract ", padding=10)
        step2.pack(fill="x", pady=(10, 0))
        chosen = settings.get("sections", list(ax.SECTIONS))
        self.want = {s: tk.BooleanVar(value=s in chosen) for s in ax.SECTIONS}
        labels = {"cfs": "CFS  -  Consolidated Financial Statements (Balance Sheet, P&L, Cash Flow + Other expenses note)",
                  "cfsn": "CFSN  -  Notes to the Consolidated Financial Statements"}
        for s in ax.SECTIONS:
            ttk.Checkbutton(step2, text=labels[s], variable=self.want[s]).pack(anchor="w", pady=1)

        # Step 3: extract
        step3 = ttk.Frame(main, padding=(0, 12, 0, 8))
        step3.pack(fill="x")
        self.go = ttk.Button(step3, text="3.  Extract", style="Big.TButton", command=self.start)
        self.go.pack(side="left")
        self.progress = ttk.Progressbar(step3, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=12)
        self.status = tk.StringVar(value="Choose a folder, then click Extract.")
        ttk.Label(main, textvariable=self.status).pack(anchor="w")

        # Results table
        cols = ("file", "company", "year", "cfs", "cfsn", "result")
        heads = ("Annual report", "Company", "Year", "Statements pages",
                 "Notes pages", "Result")
        widths = (190, 150, 70, 150, 110, 260)
        box = ttk.Frame(main)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w", stretch=c in ("result", "file"))
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("ok", foreground="#1b6e2a")
        self.tree.tag_configure("warn", foreground="#a15c00")
        self.tree.tag_configure("bad", foreground="#b00020")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_buttons())
        self.tree.bind("<Double-1>", lambda e: self.correct())

        # Bottom buttons
        bottom = ttk.Frame(main, padding=(0, 10, 0, 0))
        bottom.pack(fill="x", side="bottom", before=box)  # stays visible when the window is small
        self.open_btn = ttk.Button(bottom, text="Open results folder", command=self.open_results)
        self.open_btn.pack(side="left")
        self.fix_btn = ttk.Button(bottom, text="Correct pages of selected report...",
                                  command=self.correct)
        self.fix_btn.pack(side="left", padx=8)
        ttk.Label(bottom, style="Hint.TLabel",
                  text="Page numbers are the ones your PDF viewer shows. "
                       "If a result looks wrong, select it and correct the pages."
                  ).pack(side="left", padx=8)
        self.update_buttons()

    # ------------------------------------------------------------ actions

    def choose(self):
        d = filedialog.askdirectory(title="Choose the folder with the annual reports",
                                    initialdir=self.folder.get() or os.path.expanduser("~"))
        if d:
            self.folder.set(os.path.normpath(d))

    def out_dir(self):
        return os.path.join(self.folder.get().strip().strip('"'), ax.OUT_DIR_NAME)

    def open_results(self):
        d = self.out_dir()
        if os.path.isdir(d):
            open_path(d)
        else:
            messagebox.showinfo(APP_TITLE, "Nothing has been extracted from this folder yet.")

    def update_buttons(self):
        state = "disabled" if self.busy else "normal"
        self.go.configure(state=state)
        self.fix_btn.configure(state="normal" if self.tree.selection() and not self.busy else "disabled")

    def start(self):
        folder = self.folder.get().strip().strip('"')
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(APP_TITLE, "Please choose the folder that has the annual report PDFs.")
            return
        files = ax.list_reports(folder)
        if not files:
            messagebox.showwarning(APP_TITLE, "There are no PDF files in that folder.")
            return
        sections = [s for s in ax.SECTIONS if self.want[s].get()]
        if not sections:
            messagebox.showwarning(APP_TITLE, "Please tick at least one of CFS or CFSN.")
            return
        save_settings({"folder": folder, "sections": sections})
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        os.makedirs(self.out_dir(), exist_ok=True)
        self.busy = True
        self.update_buttons()
        self.progress.configure(maximum=len(files), value=0)
        threading.Thread(target=self.work, args=(files, self.out_dir(), sections), daemon=True).start()
        self.root.after(100, self.poll)

    def work(self, files, out_dir, sections):
        used = set()
        for k, path in enumerate(files, 1):
            name = os.path.basename(path)
            self.msgs.put(("status", f"Reading {name}  ({k} of {len(files)}) ..."))
            row = {"path": path, "out_dir": out_dir, "res": None, "base": "", "files": [],
                   "sections": sections}
            try:
                res = ax.detect(path)
                base = ax.base_name(res, path)
                if base in used:
                    base = ax.safe_name(f"{base}_{os.path.splitext(name)[0]}")
                used.add(base)
                row.update(res=res, base=base)
                for s in sections:
                    if res.pages.get(s):
                        dest = ax.output_path(out_dir, base, s, res.basis)
                        ax.write_pdf(path, res.pages[s], dest)
                        row["files"].append(dest)
            except Exception as e:  # damaged / password-protected PDF etc.
                row["error"] = str(e) or e.__class__.__name__
            self.msgs.put(("row", row))
            self.msgs.put(("progress", k))
        self.msgs.put(("done", len(files)))

    def poll(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "status":
                    self.status.set(val)
                elif kind == "progress":
                    self.progress.configure(value=val)
                elif kind == "row":
                    self.add_row(val)
                elif kind == "done":
                    self.finish(val)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def row_values(self, row):
        name = os.path.basename(row["path"])
        res = row["res"]
        if res is None:
            return (name, "", "", "", "", f"Could not read: {row['error']}"), "bad"
        wanted = row["sections"]
        shown = {s: (ax.fmt_pages(res.pages.get(s)) or "not found") if s in wanted else "not selected"
                 for s in ax.SECTIONS}
        # warnings about a section you didn't ask for don't matter
        skipped = [ax.FILE_TAG[s] for s in ax.SECTIONS if s not in wanted]
        warnings = [w for w in res.warnings if not any(w.startswith(t + " ") for t in skipped)]
        if not any(res.pages.get(s) for s in wanted):
            result, tag = "Not found - use Correct pages", "bad"
        else:
            result, tag = "Saved", "ok"
            if warnings:
                result, tag = "Saved - please check: " + "; ".join(warnings), "warn"
        company = (res.company or "").replace("_", " ")
        return (name, company, res.fy, shown["cfs"], shown["cfsn"], result), tag

    def add_row(self, row):
        values, tag = self.row_values(row)
        iid = self.tree.insert("", "end", values=values, tags=(tag,))
        self.rows[iid] = row

    def finish(self, n):
        self.busy = False
        self.update_buttons()
        saved = sum(len(r["files"]) for r in self.rows.values())
        problems = sum(1 for iid in self.rows if self.tree.item(iid, "tags")[0] != "ok")
        msg = f"Done. {saved} files saved from {n} reports into the \"{ax.OUT_DIR_NAME}\" folder."
        if problems:
            msg += f"  {problems} report(s) need a look (orange/red rows)."
        self.status.set(msg)

    # ---------------------------------------------------------- corrections

    def correct(self):
        sel = self.tree.selection()
        if not sel or self.busy:
            return
        iid = sel[0]
        row = self.rows[iid]
        if row["res"] is None:
            messagebox.showerror(APP_TITLE, f"This PDF could not be read:\n{row['error']}")
            return
        CorrectDialog(self, iid, row)

    def apply_correction(self, iid, row, base, pages):
        res = row["res"]
        for f in row["files"]:  # remove this report's earlier outputs
            try:
                os.remove(f)
            except OSError:
                pass
        row["files"] = []
        row["base"] = base
        res.pages = pages
        res.warnings = []
        for s, idx in pages.items():
            if idx and s in row["sections"]:
                dest = ax.output_path(row["out_dir"], base, s, res.basis)
                ax.write_pdf(row["path"], idx, dest)
                row["files"].append(dest)
        values = list(self.row_values(row)[0])
        values[5] = f"Saved as {base}_... (corrected by you)"
        self.tree.item(iid, values=values, tags=("ok",))
        self.status.set(f"Saved corrected files for {os.path.basename(row['path'])}.")


class CorrectDialog:
    def __init__(self, app, iid, row):
        self.app, self.iid, self.row = app, iid, row
        res = row["res"]
        top = self.top = tk.Toplevel(app.root)
        top.title("Correct pages")
        top.transient(app.root)
        top.resizable(False, False)
        f = ttk.Frame(top, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text=os.path.basename(row["path"]), font=("Segoe UI", 11, "bold")
                  ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, style="Hint.TLabel",
                  text=f"This PDF has {res.n_pages} pages. Use the page numbers your PDF viewer shows,\n"
                       "e.g. 190-193  or  83-84, 86-87  to skip pages."
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))

        self.base = tk.StringVar(value=row["base"])
        self.cfs = tk.StringVar(value=ax.fmt_pages(res.pages.get("cfs")))
        self.cfsn = tk.StringVar(value=ax.fmt_pages(res.pages.get("cfsn")))
        fields = [("File name start", self.base, "e.g. Voltas_FY2025")]
        if "cfs" in row["sections"]:
            fields.append(("Financial statements pages", self.cfs, "BS, P&L, Cash Flow, Other expenses"))
        if "cfsn" in row["sections"]:
            fields.append(("Notes pages", self.cfsn, "Notes to the consolidated statements"))
        for r, (label, var, hint) in enumerate(fields, 2):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=4)
            ttk.Entry(f, textvariable=var, width=34).grid(row=r, column=1, sticky="w", padx=8)
            ttk.Label(f, text=hint, style="Hint.TLabel").grid(row=r, column=2, sticky="w")

        btns = ttk.Frame(f, padding=(0, 14, 0, 0))
        btns.grid(row=6, column=0, columnspan=3, sticky="ew")
        ttk.Button(btns, text="Open the annual report", command=lambda: open_path(row["path"])
                   ).pack(side="left")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self.save).pack(side="right", padx=8)
        top.grab_set()

    def save(self):
        res = self.row["res"]
        base = ax.safe_name(self.base.get())
        if not base:
            messagebox.showwarning("Correct pages", "Please enter a file name start.", parent=self.top)
            return
        try:
            pages = {"cfs": ax.parse_pages(self.cfs.get(), res.n_pages),
                     "cfsn": ax.parse_pages(self.cfsn.get(), res.n_pages)}
        except ValueError as e:
            messagebox.showwarning("Correct pages", str(e), parent=self.top)
            return
        try:
            self.app.apply_correction(self.iid, self.row, base, pages)
        except OSError as e:
            messagebox.showerror("Correct pages",
                                 f"Could not save. Is one of the files open in a PDF viewer?\n\n{e}",
                                 parent=self.top)
            return
        self.top.destroy()


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
