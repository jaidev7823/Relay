# SPDX-License-Identifier: AGPL-3.0-or-later
"""Main Relevantr window.

Long operations (indexing, querying, model loading) run in worker threads and
report back to the Tk main loop via root.after, so the GUI never blocks.
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .. import __version__, pipeline
from ..config import AppConfig
from ..embed import backend_name, get_backend
from ..llm import LLMClient, LLMError
from ..rerank import Passage, Reranker
from ..store import (
    EmbeddingMismatchError,
    LegacyIndexError,
    LocationUnavailableError,
    RebuildRequiredError,
    StoreError,
    detect_legacy_chroma,
)
from .markdown_view import insert_markdown
from .settings import SettingsDialog

logger = logging.getLogger(__name__)


class RelevantrApp:
    def __init__(self):
        self.config = AppConfig.load()
        self.root = tk.Tk()
        self.root.title(f"Relevantr {__version__} - Scientific PDF Retrieval")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)

        self._embedder = None  # lazy; dropped when settings change
        self._reranker = None
        self.is_busy = False
        self._last_passages: list[Passage] = []
        self._last_answer: str | None = None
        self._last_query: str | None = None

        self._build_menu()
        self._build_toolbar()
        self._build_main()
        self._build_status_bar()

        self.refresh_status()
        self.root.after(300, self._startup_checks)

    # ------------------------------------------------------------------ UI

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Update Index", command=self.update_index)
        file_menu.add_command(label="Rebuild Index", command=self.rebuild_index)
        file_menu.add_separator()
        file_menu.add_command(label="Export Results", command=self.export_results)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Settings...", command=self.open_settings)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=5, pady=3)

        self.update_btn = ttk.Button(bar, text="Update Index", command=self.update_index)
        self.update_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.rebuild_btn = ttk.Button(bar, text="Rebuild Index", command=self.rebuild_index)
        self.rebuild_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Settings...", command=self.open_settings).pack(
            side=tk.LEFT, padx=4
        )

        # Prominent LLM toggle
        self.llm_var = tk.BooleanVar(value=self.config.llm_enabled)
        self.llm_check = ttk.Checkbutton(
            bar,
            text="Answer with LLM (off = retrieval only)",
            variable=self.llm_var,
            command=self._on_llm_toggle,
        )
        self.llm_check.pack(side=tk.RIGHT, padx=6)

        # Index status line (locations, model, counts)
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5)
        self.index_status_var = tk.StringVar(value="No index")
        ttk.Label(
            status_frame, textvariable=self.index_status_var, foreground="#555"
        ).pack(side=tk.LEFT, pady=(0, 3))

    def _build_main(self):
        container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: query + results
        left = ttk.Frame(container)
        container.add(left, weight=2)

        query_frame = ttk.LabelFrame(left, text="Ask a Question")
        query_frame.pack(fill=tk.X, pady=(0, 5))
        self.query_text = scrolledtext.ScrolledText(
            query_frame, height=3, wrap=tk.WORD, font=("Arial", 12)
        )
        self.query_text.pack(fill=tk.X, padx=5, pady=5)
        btns = ttk.Frame(query_frame)
        btns.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.ask_btn = ttk.Button(btns, text="Ask", command=self.run_query)
        self.ask_btn.pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Clear", command=lambda: self.query_text.delete("1.0", tk.END)
        ).pack(side=tk.LEFT, padx=5)

        results_frame = ttk.LabelFrame(left, text="Results")
        results_frame.pack(fill=tk.BOTH, expand=True)
        self.results_text = scrolledtext.ScrolledText(
            results_frame, wrap=tk.WORD, font=("Arial", 12)
        )
        self.results_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Right: sources + passage content + progress
        right = ttk.Frame(container)
        container.add(right, weight=1)

        sources_frame = ttk.LabelFrame(right, text="Sources")
        sources_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        holder = ttk.Frame(sources_frame)
        holder.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.sources_tree = ttk.Treeview(
            holder, columns=("File", "Page"), show="tree headings", height=8
        )
        self.sources_tree.heading("#0", text="Passage")
        self.sources_tree.heading("File", text="File")
        self.sources_tree.heading("Page", text="Page")
        self.sources_tree.column("#0", width=90)
        self.sources_tree.column("File", width=200)
        self.sources_tree.column("Page", width=50)
        scroll = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.sources_tree.yview)
        self.sources_tree.configure(yscrollcommand=scroll.set)
        self.sources_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sources_tree.bind("<Double-1>", self.show_source_content)

        content_frame = ttk.LabelFrame(
            right, text="Source Content (double-click a source to view)"
        )
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.source_content_text = scrolledtext.ScrolledText(
            content_frame, wrap=tk.WORD, font=("Arial", 11), height=10
        )
        self.source_content_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        progress_frame = ttk.LabelFrame(right, text="Progress")
        progress_frame.pack(fill=tk.X)
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(padx=5, pady=2)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, padx=5, pady=(0, 5))

    def _build_status_bar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bar, textvariable=self.status_var).pack(side=tk.LEFT, padx=5, pady=2)

    # ---------------------------------------------------------- state/status

    def invalidate_models(self):
        """Drop cached embedder/reranker after settings changed."""
        self._embedder = None
        self._reranker = None

    def get_embedder(self):
        if self._embedder is None:
            self._embedder = get_backend(self.config)
        return self._embedder

    def get_reranker(self):
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker

    def refresh_status(self):
        try:
            info = pipeline.index_info(self.config)
        except StoreError:
            self.index_status_var.set(
                f"No index yet | DB: {self.config.db_dir} | "
                f"PDFs: {self.config.pdf_dir or '(not set)'} | "
                f"Embeddings: {backend_name(self.config)}"
            )
            return
        pdf_note = "" if info["pdf_dir_available"] else "  [PDF dir unavailable!]"
        self.index_status_var.set(
            f"PDFs: {info['pdf_dir']}{pdf_note} | DB: {info['db_dir']} | "
            f"Embeddings: {info['embedding_model']} | "
            f"{info['documents']} documents, {info['chunks']} chunks"
        )

    def _startup_checks(self):
        legacy = detect_legacy_chroma(self.config.db_dir, Path.cwd())
        if legacy:
            messagebox.showinfo(
                "Old index found",
                f"'{legacy}' contains a Relevantr v1 (ChromaDB) index.\n\n"
                "Relevantr v2 uses a new database (LanceDB) and cannot read "
                "it. Please rebuild the index from your PDF folder; the old "
                "directory can be deleted.",
            )
        reason = pipeline.check_rebuild_needed(self.config, backend_name(self.config))
        if reason:
            self._offer_rebuild(reason)

    def _offer_rebuild(self, reason: str):
        est = pipeline.estimate_rebuild_seconds(self.config)
        est_note = f"\n\nEstimated time: about {_fmt_seconds(est)}." if est else ""
        if messagebox.askyesno(
            "Rebuild needed",
            f"The index must be rebuilt: {reason}{est_note}\n\n"
            "Until you rebuild, the existing index keeps working with its "
            "old settings.\n\nRebuild now?",
        ):
            self.rebuild_index(confirmed=True)

    def _on_llm_toggle(self):
        self.config.llm_enabled = self.llm_var.get()
        self.config.save()

    # ------------------------------------------------------------- threading

    def _run_in_thread(self, work, on_done):
        """Run work() in a thread; deliver (result, error) to on_done on the
        Tk main loop."""

        def runner():
            try:
                result = work()
                error = None
            except Exception as exc:  # noqa: BLE001 - reported to the user
                logger.error("Background task failed: %s\n%s", exc, traceback.format_exc())
                result, error = None, exc
            self.root.after(0, lambda: on_done(result, error))

        threading.Thread(target=runner, daemon=True).start()

    def _progress(self, current, total, message):
        def apply():
            if total:
                self.progress_bar["value"] = 100.0 * current / total
            self.progress_var.set(message)

        self.root.after(0, apply)

    def _set_busy(self, busy: bool, message: str = ""):
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.ask_btn, self.update_btn, self.rebuild_btn):
            widget.config(state=state)
        if message:
            self.status_var.set(message)
        if not busy:
            self.progress_bar["value"] = 0
            self.progress_var.set("Ready")

    def _report_error(self, exc: Exception, title: str):
        if isinstance(exc, (EmbeddingMismatchError, RebuildRequiredError)):
            reason = getattr(exc, "reason", str(exc))
            self._offer_rebuild(reason)
        elif isinstance(exc, (LocationUnavailableError, LegacyIndexError, LLMError)):
            messagebox.showerror(title, str(exc))
        else:
            messagebox.showerror(title, f"{type(exc).__name__}: {exc}")
        self.status_var.set(f"{title} failed")

    # -------------------------------------------------------------- indexing

    def update_index(self):
        if self.is_busy:
            return
        if not self._check_manifest_pdf_dir():
            return
        self._set_busy(True, "Updating index...")

        def work():
            return pipeline.update_index(
                self.config, self.get_embedder(), progress=self._progress
            )

        def done(summary, error):
            self._set_busy(False)
            if error:
                self._report_error(error, "Update index")
                return
            self.refresh_status()
            self.status_var.set(summary.describe())
            messagebox.showinfo("Update index", summary.describe())

        self._run_in_thread(work, done)

    def rebuild_index(self, confirmed: bool = False):
        if self.is_busy:
            return
        if not self.config.pdf_dir:
            messagebox.showerror(
                "Rebuild index", "Choose a PDF directory in Settings first."
            )
            return
        if not confirmed:
            est = pipeline.estimate_rebuild_seconds(self.config)
            est_note = f"\n\nEstimated time: about {_fmt_seconds(est)}." if est else ""
            if not messagebox.askyesno(
                "Rebuild index",
                "Re-extract and re-embed ALL PDFs from scratch? The current "
                f"index will be replaced.{est_note}",
            ):
                return
        self._set_busy(True, "Rebuilding index...")

        def work():
            return pipeline.build_index(
                self.config, self.get_embedder(), progress=self._progress
            )

        def done(summary, error):
            self._set_busy(False)
            if error:
                self._report_error(error, "Rebuild index")
                return
            self.refresh_status()
            self.status_var.set(summary.describe())
            messagebox.showinfo("Rebuild index", summary.describe())

        self._run_in_thread(work, done)

    def _check_manifest_pdf_dir(self) -> bool:
        """If the index was moved and its recorded PDF dir is gone, let the
        user re-confirm the new location once (updates the manifest)."""
        try:
            info = pipeline.index_info(self.config)
        except StoreError:
            return True  # no index yet - build path will validate
        if info["pdf_dir_available"]:
            return True
        if not messagebox.askyesno(
            "PDF directory not found",
            f"The PDF directory recorded in the index\n\n  {info['pdf_dir']}\n\n"
            "is not available (moved index, or unmounted drive?).\n"
            "Choose the current location of the same PDF folder?",
        ):
            return False
        chosen = filedialog.askdirectory(title="Locate the PDF directory")
        if not chosen:
            return False
        try:
            pipeline.repoint_pdf_dir(self.config, chosen)
        except StoreError as exc:
            messagebox.showerror("PDF directory", str(exc))
            return False
        self.config.pdf_dir = chosen
        self.config.save()
        self.refresh_status()
        return True

    # --------------------------------------------------------------- queries

    def run_query(self):
        if self.is_busy:
            return
        question = self.query_text.get("1.0", tk.END).strip()
        if not question:
            messagebox.showwarning("Ask", "Please enter a question.")
            return
        self._set_busy(True, "Searching...")
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, "Searching...\n")
        self._clear_sources()
        use_llm = self.llm_var.get()

        def work():
            reranker = self.get_reranker() if self.config.use_reranker else None
            passages = pipeline.query_index(
                self.config, self.get_embedder(), question, reranker=reranker
            )
            answer = None
            if use_llm and passages:
                client = LLMClient.from_config(self.config)
                answer = client.answer(question, passages)
            return passages, answer

        def done(result, error):
            self._set_busy(False)
            self.results_text.delete("1.0", tk.END)
            if error:
                self._report_error(error, "Query")
                self.results_text.insert(tk.END, f"Error: {error}")
                return
            passages, answer = result
            self._last_passages, self._last_answer = passages, answer
            self._last_query = question
            self._display_passages(passages, answer)
            mode = "LLM answer" if answer else "retrieval only"
            self.status_var.set(f"Found {len(passages)} passages ({mode})")

        self._run_in_thread(work, done)

    def _display_passages(self, passages: list[Passage], answer: str | None):
        if not passages:
            self.results_text.insert(tk.END, "No matching passages found.")
            return
        if answer:
            insert_markdown(self.results_text, answer)
        else:
            self.results_text.insert(
                tk.END,
                "Retrieval-only mode (LLM off) - the most relevant passages:\n\n",
            )
            for i, p in enumerate(passages, 1):
                self.results_text.insert(
                    tk.END,
                    f"[{i}] {p.source} (Page: {p.page})\n{p.text.strip()}\n\n"
                    + "-" * 60
                    + "\n\n",
                )
        for i, p in enumerate(passages):
            self.sources_tree.insert(
                "", tk.END, text=f"Passage {i + 1}", values=(p.source, p.page),
                tags=(str(i),),
            )
        self.source_content_text.delete("1.0", tk.END)
        self.source_content_text.insert(
            tk.END, "Double-click on a source above to view its content..."
        )

    def show_source_content(self, _event):
        selection = self.sources_tree.selection()
        if not selection:
            return
        tags = self.sources_tree.item(selection[0], "tags")
        if not tags:
            return
        try:
            p = self._last_passages[int(tags[0])]
        except (ValueError, IndexError):
            return
        self.source_content_text.delete("1.0", tk.END)
        header = f"Source: {p.source}\nPage: {p.page}\n" + "=" * 50 + "\n\n"
        self.source_content_text.insert(tk.END, header + p.text)

    def _clear_sources(self):
        for item in self.sources_tree.get_children():
            self.sources_tree.delete(item)
        self.source_content_text.delete("1.0", tk.END)

    # ---------------------------------------------------------------- export

    def export_results(self):
        if not self._last_passages:
            messagebox.showwarning("Export", "No query results to export.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("Markdown files", "*.md"),
                       ("All files", "*.*")],
            title="Export Results",
        )
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("Relevantr - Query Results\n")
                f.write(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Query: {self._last_query}\n\n")
                if self._last_answer:
                    f.write(f"Answer:\n{self._last_answer}\n\n")
                f.write("Passages:\n")
                for i, p in enumerate(self._last_passages, 1):
                    f.write(f"\n{i}. {p.source} (Page: {p.page})\n")
                    f.write("-" * 40 + "\n")
                    f.write(p.text.strip() + "\n")
            messagebox.showinfo("Export", f"Results exported to {filename}")
        except OSError as exc:
            messagebox.showerror("Export", f"Failed to export results: {exc}")

    # -------------------------------------------------------------- settings

    def open_settings(self):
        dialog = SettingsDialog(self.root, self.config)
        self.root.wait_window(dialog.top)
        if not dialog.saved:
            return
        self.config.save()
        self.invalidate_models()
        self.llm_var.set(self.config.llm_enabled)
        self.refresh_status()
        reason = pipeline.check_rebuild_needed(self.config, backend_name(self.config))
        if reason:
            self._offer_rebuild(reason)

    def show_about(self):
        messagebox.showinfo(
            "About Relevantr",
            f"Relevantr {__version__}\n"
            "A scientific PDF RAG (Retrieval-Augmented Generation) app.\n\n"
            "Pipeline: PDF ingest (pymupdf) -> hybrid search (LanceDB, "
            "vector + BM25) -> cross-encoder rerank -> optional LLM answer "
            "with strict source attribution.\n\n"
            "(c) 2025-2026 Erik Bitzek - CC BY-NC-SA 4.0\n"
            "https://github.com/biterik/Relevantr",
        )

    def run(self):
        self.root.mainloop()


def _fmt_seconds(seconds: float) -> str:
    if seconds < 90:
        return f"{max(1, round(seconds))} seconds"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    return f"{minutes / 60:.1f} hours"


def run_gui():
    RelevantrApp().run()
