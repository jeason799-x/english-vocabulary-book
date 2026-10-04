from copy import deepcopy
import re
import tkinter as tk
from tkinter import ttk, messagebox

from essay_library import word_count, parse_expression_lines, format_expression_lines, vocabulary_payloads, parse_essay_text
from ui_components import RoundedCard, ScrollablePanel, ui_font, english_font, cached_page


def reading_text(parent, colors, text, *, english=False):
    frame = tk.Frame(parent, bg=colors['surface'])
    frame.pack(fill='both', expand=True)
    widget = tk.Text(frame, wrap='word', relief='flat', bd=0, highlightthickness=0,
                     bg=colors['surface'], fg=colors['text'], padx=14, pady=12,
                     font=(english_font if english else ui_font)(12), spacing1=4, spacing3=8,
                     selectbackground=colors['blue_light'], selectforeground=colors['text'])
    scrollbar = ttk.Scrollbar(frame, command=widget.yview)
    scrollbar.pack(side='right', fill='y')
    widget.pack(side='left', fill='both', expand=True)
    widget.configure(yscrollcommand=scrollbar.set)
    widget.tag_configure('emphasis', font=(english_font if english else ui_font)(12, True),
                         foreground=colors['blue'])
    pieces = re.split(r'(\*\*.*?\*\*)', text, flags=re.S)
    for piece in pieces:
        if piece.startswith('**') and piece.endswith('**'):
            widget.insert('end', piece[2:-2], 'emphasis')
        else:
            widget.insert('end', piece)
    widget.configure(state='disabled')
    return widget


class EssayLibraryMixin:
    @cached_page("essays")
    def show_essays(self, selected_id=None):
        selected_id = selected_id or getattr(self, 'selected_essay_id', None)
        body = self._page('essays', '作文积累', f'{len(self.store.essays)} 篇 · 读懂，也写得出', scroll=False)
        body.columnconfigure(0, minsize=210)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        directory = RoundedCard(body, self.colors, padding=14)
        directory.configure(width=218)
        directory.grid(row=0, column=0, sticky='nsew', padx=(0, 18))
        self.button(directory.content, '+  新增作文', self.open_essay_paste, width=190).pack(fill='x', pady=(0, 16))
        query = tk.StringVar()
        self.label(directory.content, '搜索编号、标题或内容', 8, muted=True).pack(anchor='w', pady=(0, 6))
        ttk.Entry(directory.content, textvariable=query, width=23).pack(fill='x', pady=(0, 14))
        list_frame = tk.Frame(directory.content, bg=self.colors['surface'])
        list_frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(list_frame, show='tree', selectmode='browse', style='App.Treeview', height=6)
        tree.column('#0', width=184, minwidth=130, stretch=True)
        scroll = ttk.Scrollbar(list_frame, command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        tree.configure(yscrollcommand=scroll.set)
        self.essay_detail = tk.Frame(body, bg=self.colors['bg'])
        self.essay_detail.grid(row=0, column=1, sticky='nsew')
        self._displayed_essay = None

        def choose(_event=None):
            if tree.selection():
                essay = next((e for e in self.store.essays if e['id'] == tree.selection()[0]), None)
                if essay:
                    self.selected_essay_id = essay['id']
                    self._show_essay_detail(essay)

        def refresh(*_args):
            search = query.get().strip().casefold()
            tree.delete(*tree.get_children())
            visible = []
            for essay in sorted(self.store.essays, key=lambda e: e.get('updated_at', ''), reverse=True):
                searchable = '\n'.join(str(essay.get(key, '')) for key in
                                       ('code', 'title', 'topic', 'original', 'translation', 'thinking', 'collocations', 'templates'))
                if not search or search in searchable.casefold():
                    tree.insert('', 'end', iid=essay['id'], text=essay['code'])
                    visible.append(essay['id'])
            pick = getattr(self, 'selected_essay_id', None)
            if visible:
                tree.selection_set(pick if pick in visible else visible[0])
                choose()
            else:
                self._displayed_essay = None
                for child in self.essay_detail.winfo_children():
                    child.destroy()
                self.label(self.essay_detail, '没有匹配的作文' if search else '从第一篇作文开始积累', 17, emphasis=True).pack(pady=(100, 16))
                self.label(self.essay_detail, '原文、翻译、思路和搭配，都可以保存在这里。', 10, muted=True).pack()

        self.selected_essay_id = selected_id
        tree.bind('<<TreeviewSelect>>', choose)
        query.trace_add('write', refresh)
        refresh()

    def _show_essay_detail(self, essay):
        if self._displayed_essay == essay:
            return
        self._displayed_essay = deepcopy(essay)
        for child in self.essay_detail.winfo_children():
            child.destroy()
        header = RoundedCard(self.essay_detail, self.colors, padding=18)
        header.pack(fill='x', pady=(0, 16))
        top = tk.Frame(header.content, bg=self.colors['surface'])
        top.pack(fill='x')
        self.label(top, essay['code'], 12, english=True, emphasis=True).pack(side='left')
        self.button(top, '编辑', lambda: self.open_essay_editor(essay), width=74, height=34, secondary=True).pack(side='right')
        self.label(header.content, essay.get('title') or '未命名作文', 16, emphasis=True).pack(anchor='w', pady=(10, 7))
        self.label(header.content, f"{essay.get('topic', '')}    {word_count(essay['original'])} 词    {len(essay.get('collocations', []))} 条搭配", 9, muted=True).pack(anchor='w')
        notebook = ttk.Notebook(self.essay_detail)
        notebook.pack(fill='both', expand=True)
        self.essay_notebook = notebook
        bilingual = tk.Frame(notebook, bg=self.colors['surface'])
        notebook.add(bilingual, text='原文与翻译')
        bilingual.columnconfigure(0, weight=1, uniform='bilingual')
        bilingual.columnconfigure(1, weight=1, uniform='bilingual')
        bilingual.rowconfigure(1, weight=1)
        for column, (title, field, english) in enumerate((('英文原文', 'original', True), ('中文翻译', 'translation', False))):
            self.label(bilingual, title, 10, emphasis=True).grid(row=0, column=column, sticky='w', padx=14, pady=(16, 2))
            frame = tk.Frame(bilingual, bg=self.colors['surface'])
            frame.grid(row=1, column=column, sticky='nsew', padx=(0, 5) if column == 0 else (5, 0))
            reading_text(frame, self.colors, essay.get(field) or '还没有填写，可点击“编辑”补充。', english=english)
        thoughts = tk.Frame(notebook, bg=self.colors['surface'])
        notebook.add(thoughts, text='写作思路')
        phrases = tk.Frame(notebook, bg=self.colors['surface'])
        notebook.add(phrases, text='固定搭配')
        toolbar = tk.Frame(phrases, bg=self.colors['surface'])
        toolbar.pack(fill='x', padx=16, pady=14)
        self.label(toolbar, '把作文中的表达放进日常复习', 9, muted=True).pack(side='left')
        self.button(toolbar, '全部加入生词本', lambda: self._add_essay_phrases(essay), width=150, height=38).pack(side='right')
        templates = tk.Frame(notebook, bg=self.colors['surface'])
        notebook.add(templates, text='模板句型')
        builders = {
            str(thoughts): lambda: reading_text(thoughts, self.colors, essay.get('thinking') or '还没有填写写作思路。'),
            str(phrases): lambda: self._expression_cards(phrases, essay.get('collocations', []), essay, True),
            str(templates): lambda: self._expression_cards(templates, essay.get('templates', []), essay, False),
        }
        def build_selected_tab(_event=None):
            builder = builders.pop(notebook.select(), None)
            if builder:
                builder()
        notebook.bind('<<NotebookTabChanged>>', build_selected_tab)
        footer = tk.Frame(self.essay_detail, bg=self.colors['bg'])
        footer.pack(side='bottom', before=notebook, fill='x', pady=(12, 0))
        self.essay_footer = footer
        self.label(footer, '重点句以颜色标记；阅读区可选中、复制。', 8, muted=True).pack(side='left')
        self.button(footer, '删除作文', lambda: self._delete_essay(essay), width=90, height=30, secondary=True).pack(side='right')

    def _expression_cards(self, parent, rows, essay, add_to_vocabulary):
        panel = ScrollablePanel(parent, self.colors['surface'])
        panel.pack(fill='both', expand=True, padx=14, pady=12)
        if not rows:
            self.label(panel.content, '还没有填写，可点击“编辑”补充。', 10, muted=True).pack(anchor='w', padx=10, pady=15)
        for index, row in enumerate(rows, 1):
            card = RoundedCard(panel.content, self.colors, padding=15)
            card.pack(fill='x', pady=(0, 12))
            # A read-only text widget wraps both long sentences and long Chinese notes.
            text = tk.Text(card.content, wrap='word', height=3, bd=0, highlightthickness=0,
                           bg=self.colors['surface'], fg=self.colors['text'], font=english_font(11),
                           spacing3=6)
            text.pack(fill='x')
            text.tag_configure('meaning', font=ui_font(10))
            text.tag_configure('note', font=ui_font(9), foreground=self.colors['muted'])
            text.insert('end', f"{index:02d}  {row['expression']}\n")
            text.insert('end', row['meaning'] + '\n', 'meaning')
            if row.get('note'):
                text.insert('end', row['note'], 'note')
            text.configure(state='disabled')
            def resize(_event=None, widget=text):
                if not widget.winfo_exists():
                    return
                lines = widget.count('1.0', 'end', 'displaylines')
                height = max(3, (lines[0] if lines else 3) + 1)
                if int(widget.cget('height')) != height:
                    widget.configure(height=height)
            text.bind('<Configure>', resize)
            def wheel(event, viewport=panel):
                viewport.scroll_by(-event.delta / 120 * 60)
                return 'break'
            text.bind('<MouseWheel>', wheel)
            if add_to_vocabulary:
                self.button(card.content, '加入生词本', lambda r=row: self._add_essay_phrases(essay, [r]),
                            width=120, height=32, secondary=True).pack(anchor='e', pady=(8, 0))

    def _add_essay_phrases(self, essay, rows=None):
        selected = {**essay, 'collocations': rows if rows is not None else essay.get('collocations', [])}
        if not selected['collocations']:
            messagebox.showinfo('暂无搭配', '可以先编辑作文，补充固定搭配。', parent=self)
            return
        try:
            created, duplicates = self.store.add_many(vocabulary_payloads(selected))
        except (OSError, ValueError) as error:
            messagebox.showerror('未能保存', str(error), parent=self)
            return
        messagebox.showinfo('已加入生词本', f'新增 {len(created)} 条搭配，跳过 {duplicates} 条已有内容。\n可以从“今日”的学习入口开始练习。', parent=self)

    def _delete_essay(self, essay):
        if not messagebox.askyesno('删除作文', f"确定删除 {essay['code']} 吗？\n已加入生词本的搭配会保留。", parent=self):
            return
        try:
            self.store.delete_essay(essay['id'])
        except OSError as error:
            messagebox.showerror('未能删除', str(error), parent=self)
            return
        self.selected_essay_id = None
        self.show_essays()

    def open_essay_editor(self, essay=None):
        return EssayEditor(self, essay)

    def open_essay_paste(self):
        return EssayPasteDialog(self)


class EssayPasteDialog(tk.Toplevel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.title('整篇粘贴作文')
        self.geometry('1000x740')
        self.minsize(880, 620)
        self.configure(bg=owner.colors['bg'])
        self.transient(owner)
        self.grab_set()
        header = tk.Frame(self, bg=owner.colors['bg'])
        header.pack(fill='x', padx=24, pady=(20, 16))
        owner.label(header, '像发消息一样，存一篇作文', 18, emphasis=True).pack(anchor='w')
        owner.label(header, '把编号、原文、中文翻译、模板句说明和写作思路一起粘贴，软件会自动分栏。', 10, muted=True).pack(anchor='w', pady=(9, 6))
        owner.label(header, '首行例：**CET6_202512_W_02**    分栏标题例：**中文翻译：**、**写作思路：**、**固定搭配：**', 9, muted=True).pack(anchor='w')
        footer = tk.Frame(self, bg=owner.colors['bg'])
        footer.pack(side='bottom', fill='x', padx=24, pady=18)
        owner.button(footer, '识别并预览  →', self.prepare, width=165).pack(side='right')
        owner.button(footer, '取消', self.close, width=90, secondary=True).pack(side='right', padx=(0, 12))
        owner.button(footer, '分栏填写', self.manual, width=110, secondary=True).pack(side='left')
        frame = tk.Frame(self, bg=owner.colors['surface'])
        frame.pack(fill='both', expand=True, padx=24)
        self.text = tk.Text(frame, wrap='word', bd=0, highlightthickness=0, padx=18, pady=16, undo=True,
                            bg=owner.colors['surface'], fg=owner.colors['text'], insertbackground=owner.colors['blue'],
                            font=ui_font(11), spacing3=6, selectbackground=owner.colors['blue_light'])
        scrollbar = ttk.Scrollbar(frame, command=self.text.yview)
        scrollbar.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.focus_set()
        self.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        if self.text.get('1.0', 'end-1c').strip() and not messagebox.askyesno('尚未保存', '放弃已粘贴的内容并关闭吗？', parent=self):
            return
        self.destroy()

    def manual(self):
        if self.text.get('1.0', 'end-1c').strip():
            self.prepare()
        else:
            self.destroy()
            self.owner.open_essay_editor()

    def prepare(self):
        try:
            candidates = [word for word in self.owner.store.words if word.get('entry_type') == 'phrase']
            payload = parse_essay_text(self.text.get('1.0', 'end-1c'), candidates)
            if any(essay['code'].casefold() == payload['code'].casefold() for essay in self.owner.store.essays):
                raise ValueError('这个编号已在作文库中。请在目录中编辑原作文，或为新作文换一个编号。')
        except ValueError as error:
            messagebox.showwarning('还需要调整', str(error), parent=self)
            return
        self.destroy()
        return EssayEditor(self.owner, initial=payload)


class EssayEditor(tk.Toplevel):
    def __init__(self, owner, essay=None, initial=None):
        super().__init__(owner)
        self.owner, self.essay = owner, deepcopy(essay)
        self.source_text = (essay or initial or {}).get('source_text', '')
        values = essay or initial or {}
        self.title('编辑作文' if essay else '新增作文')
        self.geometry('1000x740')
        self.minsize(880, 620)
        self.configure(bg=owner.colors['bg'])
        self.transient(owner)
        self.grab_set()
        header = tk.Frame(self, bg=owner.colors['bg'])
        header.pack(fill='x', padx=24, pady=(20, 14))
        owner.label(header, '编辑作文' if essay else '确认作文内容' if initial else '新增一篇作文', 18, emphasis=True).pack(anchor='w')
        if initial:
            owner.label(header, f"已识别原文、翻译与思路 · {len(initial['collocations'])} 条搭配 · {len(initial['templates'])} 组句型。检查各页后保存。", 9, muted=True).pack(anchor='w', pady=(6, 0))
        form = tk.Frame(header, bg=owner.colors['bg'])
        form.pack(fill='x', pady=(14, 0))
        self.variables = {}
        for index, (key, label, width) in enumerate((('code', '作文编号（必填）', 24), ('title', '标题', 28), ('topic', '主题 / 类型', 22))):
            form.columnconfigure(index, weight=1)
            cell = tk.Frame(form, bg=owner.colors['bg'])
            cell.grid(row=0, column=index, sticky='ew', padx=(0, 14) if index < 2 else 0)
            owner.label(cell, label, 9).pack(anchor='w', pady=(0, 6))
            var = tk.StringVar(value=values.get(key, ''))
            self.variables[key] = var
            ttk.Entry(cell, textvariable=var, width=width).pack(fill='x')
        footer = tk.Frame(self, bg=owner.colors['bg'])
        footer.pack(side='bottom', fill='x', padx=24, pady=18)
        self.status = tk.StringVar()
        tk.Label(footer, textvariable=self.status, bg=owner.colors['bg'], fg=owner.colors['muted'], font=ui_font(9)).pack(side='left')
        owner.button(footer, '保存作文', self.save, width=140).pack(side='right')
        owner.button(footer, '取消', self.close, width=100, secondary=True).pack(side='right', padx=(0, 12))
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=24)
        self.notebook = notebook
        self.fields = {}
        for key, label in (('original', '英文原文'), ('translation', '中文翻译'), ('thinking', '写作思路'),
                           ('collocations', '固定搭配'), ('templates', '模板句型')):
            page = tk.Frame(notebook, bg=owner.colors['surface'])
            notebook.add(page, text=label)
            hint = ('每行：英文 | 中文释义 | 用法说明（可留空）。也支持从表格复制的制表符。' if key in ('collocations', 'templates')
                    else '可以保留段落；用 **重点内容** 标记值得背诵的句子。' if key in ('original', 'translation')
                    else '记录开头、分论点、例子和结尾，让写作结构清晰起来。')
            owner.label(page, hint, 9, muted=True).pack(anchor='w', padx=14, pady=12)
            frame = tk.Frame(page, bg=owner.colors['surface'])
            frame.pack(fill='both', expand=True, padx=14, pady=(0, 14))
            widget = tk.Text(frame, wrap='word', bd=0, highlightthickness=0, padx=12, pady=12,
                             bg=owner.colors['surface_alt'], fg=owner.colors['text'], insertbackground=owner.colors['blue'],
                             selectbackground=owner.colors['blue_light'], selectforeground=owner.colors['text'], undo=True,
                             font=english_font(12) if key == 'original' else ui_font(11), spacing3=6)
            scroll = ttk.Scrollbar(frame, command=widget.yview)
            scroll.pack(side='right', fill='y')
            widget.pack(side='left', fill='both', expand=True)
            widget.configure(yscrollcommand=scroll.set)
            value = values.get(key, [] if key in ('collocations', 'templates') else '')
            widget.insert('1.0', format_expression_lines(value) if isinstance(value, list) else value)
            widget.edit_modified(False)
            self.fields[key] = widget
        self.fields['original'].bind('<<Modified>>', self._update_word_count)
        self._update_word_count()
        self.initial = self.fingerprint()
        self.protocol('WM_DELETE_WINDOW', self.close)

    def _update_word_count(self, _event=None):
        self.status.set(f"原文 {word_count(self.fields['original'].get('1.0', 'end-1c'))} 词 · 保存到本机")
        self.fields['original'].edit_modified(False)

    def fingerprint(self):
        return tuple(v.get() for v in self.variables.values()) + tuple(w.get('1.0', 'end-1c') for w in self.fields.values())

    def close(self):
        if self.fingerprint() != self.initial and not messagebox.askyesno('尚未保存', '放弃未保存的修改并关闭吗？', parent=self):
            return
        self.destroy()

    def save(self):
        try:
            payload = {key: var.get() for key, var in self.variables.items()}
            payload['source_text'] = self.source_text
            for key, widget in self.fields.items():
                value = widget.get('1.0', 'end-1c').strip()
                payload[key] = parse_expression_lines(value) if key in ('collocations', 'templates') else value
            created = self.owner.store.save_essay(payload, self.essay['id'] if self.essay else None)
        except (ValueError, OSError) as error:
            messagebox.showerror('作文未保存', str(error), parent=self)
            return
        self.destroy()
        self.owner.selected_essay_id = created['id']
        self.owner.show_essays(created['id'])
