from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from bulk_import import parse_import, decode_import, split_duplicates
from vocabulary_items import item_type
from example_bank import complete_example, enrich_entry, has_example
from ui_components import ScrollablePanel, ui_font


class ImportDialog(tk.Toplevel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.colors = owner, owner.colors
        self.title("批量导入单词与搭配")
        self.geometry("900x770")
        self.minsize(800, 680)
        self.configure(bg=self.colors["bg"])
        self.transient(owner)
        self.grab_set()
        self.busy = False
        self.records = []
        self.cancelled = threading.Event()
        self.events = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self.close)
        footer = tk.Frame(self, bg=self.colors["bg"])
        footer.pack(side="bottom", fill="x", padx=24, pady=18)
        self.import_button = owner.button(footer, "导入", self.import_records, width=160)
        self.import_button.pack(side="right")
        self.import_button.configure(state="disabled")
        self.preview_button = owner.button(footer, "解析预览", self.prepare, secondary=True, width=145)
        self.preview_button.pack(side="right", padx=12)
        self.close_button = owner.button(footer, "取消", self.close, secondary=True, width=100)
        self.close_button.pack(side="left")
        panel = ScrollablePanel(self, self.colors["bg"])
        panel.pack(fill="both", expand=True, padx=24, pady=(20, 0))
        body = panel.content
        owner.label(body, "一次带进很多词", 20, emphasis=True).pack(anchor="w")
        owner.label(body, "单词和固定搭配可以混合导入，已有内容自动跳过。", 10, muted=True).pack(anchor="w", pady=(5, 15))
        row = tk.Frame(body, bg=self.colors["bg"])
        row.pack(fill="x", pady=(0, 12))
        self.file_button = owner.button(row, "选择词表文件", self.choose_file, secondary=True, width=160)
        self.file_button.pack(side="left")
        self.paste_button = owner.button(row, "粘贴词表", self.paste, secondary=True, width=140)
        self.paste_button.pack(side="left", padx=12)
        owner.label(row, "TXT / CSV / TSV，或直接粘贴 Excel 两列", 9, muted=True).pack(side="left")
        owner.label(body, "每行一条，可写“apple 苹果”或“pay attention to 注意”。也可以只填英文，再批量查词。", 9, muted=True,
                    wraplength=780, justify="left").pack(anchor="w", pady=(0, 8))
        input_frame = tk.Frame(body, bg=self.colors["surface"])
        input_frame.pack(fill="x")
        self.text = tk.Text(input_frame, height=7, wrap="none", font=ui_font(10), bg=self.colors["surface"],
                            fg=self.colors["text"], bd=0, padx=12, pady=12, highlightthickness=0, undo=True)
        scrollbar = ttk.Scrollbar(input_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.auto_lookup = tk.BooleanVar(value=True)
        self.lookup_check = tk.Checkbutton(body, text="自动补全缺少的释义和例句（无例句不导入）", variable=self.auto_lookup,
                                          bg=self.colors["bg"], fg=self.colors["text"], activebackground=self.colors["bg"],
                                          selectcolor=self.colors["surface"], font=ui_font(10), bd=0)
        self.lookup_check.pack(anchor="w", pady=12)
        table_frame = tk.Frame(body, bg=self.colors["surface"])
        table_frame.pack(fill="x")
        self.tree = ttk.Treeview(table_frame, columns=("word", "type", "meaning", "status"), show="headings", style="App.Treeview", height=5)
        for key, label, width in (("word", "英文内容", 220), ("type", "类型", 90), ("meaning", "中文释义", 280), ("status", "状态", 170)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=key in ("word", "meaning"))
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="x")
        self.status = tk.StringVar(value="先粘贴或选择文件，再点击“解析预览”。")
        tk.Label(body, textvariable=self.status, font=ui_font(9), bg=self.colors["bg"], fg=self.colors["muted"],
                 anchor="w", justify="left", wraplength=780).pack(fill="x", pady=14)
        self.text.bind("<<Modified>>", self.edited)
        self.poll_job = self.after(100, self.poll)

    def edited(self, event=None):
        if self.text.edit_modified():
            if not self.busy:
                self.import_button.configure(state="disabled")
                self.records = []
            self.text.edit_modified(False)

    def paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self.status.set("剪贴板里没有可粘贴的文本。")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_modified(False)
        self.prepare()

    def choose_file(self):
        path = filedialog.askopenfilename(parent=self, title="选择词表", filetypes=[("词表文件", "*.txt *.csv *.tsv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            text = decode_import(Path(path).read_bytes())
        except (OSError, UnicodeDecodeError) as error:
            messagebox.showwarning("无法读取词表", str(error), parent=self)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_modified(False)
        self.prepare()

    def prepare(self):
        if self.busy:
            return
        self.source = self.text.get("1.0", "end-1c")
        try:
            parsed, self.parse_errors = parse_import(self.source)
        except Exception as error:
            self.status.set("无法解析词表：" + str(error))
            self.import_button.configure(state="disabled")
            return
        self.records, self.duplicates = split_duplicates(parsed, self.owner.store.words)
        self.tree.delete(*self.tree.get_children())
        for i, record in enumerate(self.records):
            self.show_record(i, record, "可导入" if record["meaning"] and has_example(complete_example(record)) else "待补全释义 / 例句")
        self.status.set(f"待导入 {len(self.records)} 条，跳过重复 {self.duplicates} 条，无法识别 {len(self.parse_errors)} 行。" +
                        ("\n" + "；".join(self.parse_errors[:3]) if self.parse_errors else ""))
        self.import_button.configure(state="normal" if self.records else "disabled")

    def show_record(self, index, record, status):
        values = (record["word"], "固定搭配" if item_type(record) == "phrase" else "单词", record.get("meaning", ""), status)
        if self.tree.exists(str(index)):
            self.tree.item(str(index), values=values)
        else:
            self.tree.insert("", "end", iid=str(index), values=values)

    def import_records(self):
        if self.busy:
            return
        if not self.records or self.source != self.text.get("1.0", "end-1c"):
            self.prepare()
            return
        self.busy = True
        self.text.configure(state="disabled")
        for button in (self.preview_button, self.import_button, self.file_button, self.paste_button):
            button.configure(state="disabled")
        self.lookup_check.configure(state="disabled")
        self.close_button.configure(text="取消导入")
        self.status.set("正在整理词表；完成后统一保存，取消不会留下部分导入。")
        auto = self.auto_lookup.get()
        records = [dict(r) for r in self.records]
        def worker():
            ready, failed = [], []
            for i, record in enumerate(records):
                if self.cancelled.is_set():
                    return
                error = None
                record = complete_example(record)
                if (not record["meaning"] or not has_example(record)) and auto:
                    self.events.put(("progress", i, record, "正在查询"))
                    try:
                        record = enrich_entry(record, self.owner.lookup_word)
                    except Exception as problem:
                        error = str(problem)
                if record.get("meaning", "").strip() and has_example(record):
                    ready.append(record)
                    status = "待保存"
                else:
                    failed.append(record)
                    status = error or "缺少释义或英文例句，未导入"
                self.events.put(("progress", i, record, status))
            if not self.cancelled.is_set():
                self.events.put(("done", ready, failed))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, index, record, status = event
                    self.show_record(index, record, status)
                    self.tree.see(str(index))
                    self.status.set(f"正在处理 {index + 1}/{len(self.records)}：{record['word']} · {status}")
                else:
                    self.finish(event[1], event[2])
        except queue.Empty:
            pass
        self.poll_job = self.after(100, self.poll)

    def finish(self, ready, failed):
        try:
            created, additional_duplicates = self.owner.store.add_many(ready)
        except (OSError, ValueError) as error:
            self.busy = False
            self.import_button.configure(state="normal")
            self.text.configure(state="normal")
            self.preview_button.configure(state="normal")
            self.file_button.configure(state="normal")
            self.paste_button.configure(state="normal")
            self.lookup_check.configure(state="normal")
            self.status.set("保存失败，原有词库未改变，可重试：" + str(error))
            return
        self.busy = False
        self.status.set(f"已导入 {len(created)} 条；跳过重复 {self.duplicates + additional_duplicates} 条；未导入 {len(failed) + len(self.parse_errors)} 条。" +
                        (" 缺少释义或例句的条目可补全后重试。" if failed else ""))
        created_by_word = {w["word"]: w for w in created}
        for i, record in enumerate(self.records):
            saved = created_by_word.get(record["word"])
            if saved:
                self.show_record(i, saved, "已导入")
        self.close_button.configure(text="完成")
        self.text.configure(state="normal")
        self.preview_button.configure(state="normal")
        self.file_button.configure(state="normal")
        self.paste_button.configure(state="normal")
        self.lookup_check.configure(state="normal")
        self.records = []
        if self.owner.current_page == "words":
            self.owner.show_words()
        else:
            self.owner.show_home()

    def close(self):
        self.cancelled.set()
        self.after_cancel(self.poll_job)
        self.destroy()
