"""Desktop window: choose a Paratext project and the checks, run them, open the HTML report in the browser.

Standard library only (tkinter). The checks run in a background thread; the window shows the progress.
Projects are listed from the Paratext projects folder (read only); any other folder can be chosen too.
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, Button, Frame, Label, StringVar, Tk, filedialog, messagebox, ttk

from checker.books import DEUTEROCANON, EXTRA_MATERIAL, NEW_TESTAMENT, OLD_TESTAMENT
from checker.checks import PROJECT_CHECKS
from checker.cli import CHECK_DESCRIPTIONS, TEXT_CHECKS, project_books, run_checks, write_reports
from checker.html_report import TXT_FOLDER

TITLE = "Scripture checker"
# Usual places of the Paratext projects folder; the registry is asked first.
PARATEXT_FOLDERS = ("C:/My Paratext 9 Projects", "C:/My Paratext 8 Projects", "D:/My Paratext 9 Projects")
# Window and exe icon; build_exe.bat puts it next to this module inside the exe.
ICON = Path(__file__).with_name("icon.ico")
REPORTS_FOLDER =Path.home() / "Documents" / "Scripture checker reports"


def paratext_folder() -> Path | None:
    """The Paratext projects folder: from the registry (Paratext 8/9 write it there), else a usual place."""
    try:
        import winreg

        for key_path in (r"SOFTWARE\WOW6432Node\Paratext\8", r"SOFTWARE\Paratext\8"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    folder = Path(winreg.QueryValueEx(key, "Settings_Directory")[0])
                    if folder.is_dir():
                        return folder
            except OSError:
                continue
    except ImportError:  # not Windows
        pass
    return next((Path(folder) for folder in PARATEXT_FOLDERS if Path(folder).is_dir()), None)


def find_projects(folder: Path | None) -> dict[str, Path]:
    """Project name -> folder, for every sub-folder with Settings.xml and books."""
    if not folder:
        return {}
    projects = {}
    for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if (child / "Settings.xml").is_file() and not child.name.startswith(("_", ".")):
            projects[child.name] = child
    return projects


def default_report_dir(project: Path, paratext: Path | None) -> Path:
    """Next to the project (`<project>_report`), but never inside the Paratext folder: Paratext owns it."""
    if paratext and paratext.resolve() in project.resolve().parents:
        return REPORTS_FOLDER / f"{project.name}_report"
    return project.parent / f"{project.name}_report"


class CheckerWindow:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.paratext = paratext_folder()
        self.projects = find_projects(self.paratext)
        self.events: queue.Queue = queue.Queue()


        root.title(TITLE)
        root.minsize(760, 780)
        frame = ttk.Frame(root, padding=14)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Project:").grid(row=0, column=0, sticky="w")
        self.project = StringVar()
        self.project_box = ttk.Combobox(frame, textvariable=self.project, values=list(self.projects))
        self.project_box.grid(row=0, column=1, sticky="ew", padx=6)
        self.project_box.bind("<<ComboboxSelected>>", lambda _: self._project_changed())
        ttk.Button(frame, text="Browse...", command=self._browse_project).grid(row=0, column=2)
        hint = (f"Projects from {self.paratext}" if self.paratext
                else "Paratext projects folder not found: use Browse")
        ttk.Label(frame, text=hint, foreground="gray").grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(frame, text="Reports:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.report_dir = StringVar()
        ttk.Entry(frame, textvariable=self.report_dir).grid(row=2, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(frame, text="Browse...", command=self._browse_reports).grid(row=2, column=2, pady=(8, 0))

        self.books = BookPicker(frame)
        self.books.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(12, 0))

        checks = ttk.Frame(frame)
        checks.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=12)
        frame.rowconfigure(4, weight=1)
        self.selected: dict[str, BooleanVar] = {}
        for column, (title, names, on) in enumerate((("Text checks", TEXT_CHECKS, True),
                                                     ("Checks of the whole project", list(PROJECT_CHECKS), False))):
            box = ttk.LabelFrame(checks, text=title, padding=8)
            box.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else 0)
            checks.columnconfigure(column, weight=1)
            for row, name in enumerate(names):
                var = self.selected[name] = BooleanVar(value=on)
                button = ttk.Checkbutton(box, text=name, variable=var)
                button.grid(row=row, column=0, sticky="w")
                _Tooltip(button, CHECK_DESCRIPTIONS.get(name, ""))
            buttons = ttk.Frame(box)
            buttons.grid(row=len(names), column=0, sticky="w", pady=(6, 0))
            ttk.Button(buttons, text="All", width=6,
                       command=lambda n=names: self._set(n, True)).grid(row=0, column=0)
            ttk.Button(buttons, text="None", width=6,
                       command=lambda n=names: self._set(n, False)).grid(row=0, column=1, padx=4)

        self.run_button = ttk.Button(frame, text="Run checks", command=self._run)
        self.run_button.grid(row=5, column=0, columnspan=2, sticky="w")
        opening = ttk.Frame(frame)
        opening.grid(row=5, column=2, sticky="e")
        self.folder_button = ttk.Button(opening, text="Open txt folder", command=self._open_folder, state="disabled")
        self.folder_button.grid(row=0, column=0, padx=(0, 6))
        self.open_button = ttk.Button(opening, text="Open report", command=self._open, state="disabled")
        self.open_button.grid(row=0, column=1)
        # The buttons open the reports in the Reports folder, also ones of an earlier run.
        self.report_dir.trace_add("write", lambda *_: self._refresh_buttons())
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self.status = StringVar(value="Choose a project and press Run checks.")
        ttk.Label(frame, textvariable=self.status, wraplength=720).grid(row=7, column=0, columnspan=3, sticky="w")
        root.after(100, self._poll)

    def _set(self, names, value: bool) -> None:
        for name in names:
            self.selected[name].set(value)

    def _project_path(self) -> Path | None:
        text = self.project.get().strip()
        if not text:
            return None
        return self.projects.get(text, Path(text))

    def _project_changed(self) -> None:
        project = self._project_path()
        if project:
            self.report_dir.set(str(default_report_dir(project, self.paratext)))
        books = []
        if project and (project / "Settings.xml").is_file():
            try:
                books = project_books(project)
            except Exception:  # unreadable Settings.xml: Run shows the error
                books = []
        self.books.set_books(books)

    def _browse_project(self) -> None:
        folder = filedialog.askdirectory(title="Choose a Paratext project folder",
                                         initialdir=str(self.paratext or Path.home()))
        if folder:
            self.project.set(folder)
            self._project_changed()

    def _browse_reports(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder for the reports")
        if folder:
            self.report_dir.set(folder)

    def _run(self) -> None:
        project = self._project_path()
        if not project or not (project / "Settings.xml").is_file():
            messagebox.showerror(TITLE, "Choose a Paratext project folder (a folder with Settings.xml).")
            return
        checks = [name for name, var in self.selected.items() if var.get()]
        if not checks:
            messagebox.showerror(TITLE, "Choose at least one check.")
            return
        if self.books.codes() and not self.books.selected:
            messagebox.showerror(TITLE, "Choose at least one book.")
            return
        # None = every file of the folder, also one that is not in the list.
        books = None if self.books.all_selected() else self.books.selected_codes()
        report_dir = Path(self.report_dir.get().strip() or default_report_dir(project, self.paratext))
        self.report_dir.set(str(report_dir))
        self.run_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=1)
        threading.Thread(target=self._work, args=(project, checks, books, report_dir), daemon=True).start()

    def _work(self, project: Path, checks: list[str], books: list[str] | None, report_dir: Path) -> None:
        """Runs in the background thread; talks to the window only through the queue."""
        try:
            skipped: dict[str, str] = {}
            notes: dict[str, str] = {}
            progress = lambda done, total, what: self.events.put(("progress", done, total, what))  # noqa: E731
            findings = list(run_checks(project, checks, books, None, skipped, progress, notes))
            self.events.put(("progress", 1, 1, "writing the reports"))
            results = write_reports(project, findings, checks, report_dir, True, skipped, notes)
            self.events.put(("done", results, report_dir / "index.html"))
        except Exception:  # shown to the user, the window stays open
            self.events.put(("error", traceback.format_exc()))

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total, what = event
                    self.progress.configure(value=done, maximum=total)
                    self.status.set(f"Checking: {what}")
                elif event[0] == "done":
                    _, results, index = event
                    errors = sum(r.errors for r in results)
                    warnings = sum(r.warnings for r in results)
                    self.status.set(f"Done: {errors} errors, {warnings} warnings. Report: {index}")
                    self.run_button.configure(state="normal")
                    self._refresh_buttons()
                    self._open()
                elif event[0] == "error":
                    self.status.set("The checks stopped with an error.")
                    self.run_button.configure(state="normal")
                    messagebox.showerror(TITLE, f"The checks stopped with an error:\n\n{event[1][-2000:]}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _report_paths(self) -> tuple[Path, Path] | None:
        """(index.html, txt folder) of the Reports folder."""
        text = self.report_dir.get().strip()
        if not text:
            return None
        folder = Path(text)
        return folder / "index.html", folder / TXT_FOLDER

    def _refresh_buttons(self) -> None:
        paths = self._report_paths()
        running = str(self.run_button.cget("state")) == "disabled"
        self.open_button.configure(state="normal" if paths and paths[0].is_file() and not running else "disabled")
        self.folder_button.configure(state="normal" if paths and paths[1].is_dir() and not running else "disabled")

    def _open(self) -> None:
        paths = self._report_paths()
        if paths and paths[0].is_file():
            if hasattr(os, "startfile"):
                os.startfile(paths[0])  # the default browser on Windows
            else:
                webbrowser.open(paths[0].as_uri())

    def _open_folder(self) -> None:
        paths = self._report_paths()
        if paths and paths[1].is_dir():
            if hasattr(os, "startfile"):
                os.startfile(paths[1])  # Explorer
            else:
                webbrowser.open(paths[1].as_uri())


class BookPicker(ttk.LabelFrame):
    """The books of the project, like the Paratext Books dialog: group buttons on the left, books on the right.

    A click on a book selects or clears it. A group button selects only that group when every book is selected
    (the start), adds the group otherwise, and clears the group when all its books are selected.
    """

    ROWS = 14
    GROUPS = (("Old Testament", OLD_TESTAMENT), ("New Testament", NEW_TESTAMENT),
              ("Deuterocanon", DEUTEROCANON), ("Extra material", EXTRA_MATERIAL))
    ON, OFF = ("#0a64c8", "white"), ("white", "black")  # background, text

    def __init__(self, parent) -> None:
        super().__init__(parent, text="Books", padding=8)
        self.columnconfigure(1, weight=1)
        self.books: list[tuple[str, str]] = []
        self.selected: set[str] = set()
        self.labels: dict[str, Label] = {}
        side = ttk.Frame(self)
        side.grid(row=0, column=0, sticky="nw", padx=(0, 8))
        self.all_button = Button(side, text="All books", width=16, command=self._select_all)
        self.all_button.grid(row=0, column=0, sticky="ew", pady=1)
        self.group_buttons: list[tuple[Button, frozenset[str]]] = []
        for row, (title, codes) in enumerate(self.GROUPS, start=1):
            button = Button(side, text=title, width=16, command=lambda c=codes: self._toggle_group(c))
            button.grid(row=row, column=0, sticky="ew", pady=1)
            self.group_buttons.append((button, codes))
        Button(side, text="Deselect all", width=16, command=self._clear).grid(
            row=len(self.GROUPS) + 1, column=0, sticky="ew", pady=(10, 1))
        self.book_area = Frame(self, background="white", relief="sunken", borderwidth=1)
        self.book_area.grid(row=0, column=1, sticky="nsew")
        self.count = StringVar()
        ttk.Label(self, textvariable=self.count, foreground="gray").grid(row=1, column=1, sticky="w", pady=(4, 0))
        self._show()

    def set_books(self, books: list[tuple[str, str]]) -> None:
        """New project: show its books, all selected."""
        for label in self.labels.values():
            label.destroy()
        self.labels.clear()
        self.books = books
        for index, (code, name) in enumerate(books):
            text = f"{code}  {name}" if name else code
            label = Label(self.book_area, text=text, anchor="w", width=18, padx=4, cursor="hand2")
            label.grid(row=index % self.ROWS, column=index // self.ROWS, sticky="w")
            label.bind("<Button-1>", lambda _event, c=code: self._toggle(c))
            self.labels[code] = label
        self.selected = set(self.codes())
        self._show()

    def codes(self) -> list[str]:
        return [code for code, _ in self.books]

    def all_selected(self) -> bool:
        return self.selected == set(self.codes())

    def selected_codes(self) -> list[str]:
        return [code for code in self.codes() if code in self.selected]

    def _toggle(self, code: str) -> None:
        self.selected ^= {code}
        self._show()

    def _toggle_group(self, group: frozenset[str]) -> None:
        present = group & set(self.codes())
        if not present:
            return
        if self.all_selected():
            self.selected = set(present)
        elif present <= self.selected:
            self.selected -= present
        else:
            self.selected |= present
        self._show()

    def _select_all(self) -> None:
        self.selected = set(self.codes())
        self._show()

    def _clear(self) -> None:
        self.selected = set()
        self._show()

    def _show(self) -> None:
        for code, label in self.labels.items():
            background, foreground = self.ON if code in self.selected else self.OFF
            label.configure(background=background, foreground=foreground)
        codes = set(self.codes())
        everything = bool(codes) and self.all_selected()
        self.all_button.configure(relief="sunken" if everything else "raised")
        for button, group in self.group_buttons:
            present = group & codes
            pressed = bool(present) and present <= self.selected and not everything
            button.configure(state="normal" if present else "disabled", relief="sunken" if pressed else "raised")
        if codes:
            self.count.set(f"{len(self.selected)} of {len(codes)} books selected. "
                           "Click a book to select or clear it.")
        else:
            self.count.set("Choose a project to see its books.")


class _Tooltip:
    """The description of a check, shown while the mouse is over its name."""

    def __init__(self, widget, text: str) -> None:
        self.widget, self.text, self.window = widget, text, None
        if text:
            widget.bind("<Enter>", self._show)
            widget.bind("<Leave>", self._hide)

    def _show(self, _event) -> None:
        from tkinter import Label, Toplevel

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
        self.window = Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        Label(self.window, text=self.text, wraplength=420, justify="left", background="#ffffe0",
              relief="solid", borderwidth=1, padx=6, pady=4).pack()

    def _hide(self, _event) -> None:
        if self.window:
            self.window.destroy()
            self.window = None


def main() -> None:
    root = Tk()
    if ICON.is_file():
        try:
            root.iconbitmap(default=str(ICON))  # also for the dialogs of the window
        except Exception:  # not Windows: .ico is not supported, keep the default icon
            pass
    CheckerWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
