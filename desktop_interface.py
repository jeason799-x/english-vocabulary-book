from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk

from review_engine import PracticeSession
from vocabulary_items import item_type, answer_matches, expression_pattern, mask_example
from import_dialog import ImportDialog
from essay_interface import EssayLibraryMixin
from example_bank import complete_example, enrich_entry, has_example, repair_example_data
from ui_components import (palette, app_icon, line_icon, configure_fonts, load_bundled_fonts, enable_dark_titlebar, ui_font, english_font,
                           GradientRoundedButton, RoundedCard, WordCanvas, ScrollablePanel, ToolTip, cached_page, SceneFrame, SceneLabel, SegmentedChoice, NavigationButton)


class VocabularyWindow(EssayLibraryMixin, tk.Tk):
    def __init__(self, store, lookup_word, speech, version):
        load_bundled_fonts()
        super().__init__()
        self.store, self.lookup_word, self.speech = store, lookup_word, speech
        self.version = version
        configure_fonts(self)
        self.title("英语生词本 · 拾词")
        self.geometry("1260x820")
        self.minsize(1040, 700)
        self.option_add("*Font", ui_font(10))
        self.icon_image = ImageTk.PhotoImage(app_icon(128))
        self.iconphoto(True, self.icon_image)
        self.session = None
        self.feedback = None
        self.current_page = "home"
        self.finished_words = []
        self._page_animation_job = None
        self._page_fade_items = []
        self._scroll_animation_job = None
        self._speech_job = None
        self._speech_owner = None
        self._example_repair_busy = False
        self._example_repair_cancel = threading.Event()
        self._example_repair_job = None
        self._page_cache = {}
        self._apply_theme()
        self.after(20, lambda: enable_dark_titlebar(self))
        checkpoint = self.store.data.get("active_session")
        if checkpoint:
            try:
                self.session = PracticeSession.restore(checkpoint)
            except (KeyError, TypeError, ValueError):
                messagebox.showwarning("进度读取失败", "这一组的练习进度无法读取。单词与已保存的复习记录仍在。", parent=self)
        self.show_home()
        self.bind("<Return>", self._return_key)
        self.bind("<space>", self._space_key)
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Escape>", self._escape_key)
        for i in range(1, 5):
            self.bind(str(i), lambda e, n=i: self._number_key(n))
        self.bind_all("<MouseWheel>", self._mousewheel, add="+")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.speech.start()
        self._example_repair_job = self.after(150, self._fill_missing_examples)

    def _fill_missing_examples(self):
        self._example_repair_job = None
        if self._example_repair_busy or self._example_repair_cancel.is_set():
            return
        missing = [deepcopy(word) for word in self.store.words if not has_example(word)]
        if not missing:
            self._sync_example_health()
            return
        self._example_repair_busy = True
        events = queue.Queue()
        self._sync_example_health()

        def worker():
            updates = {}
            for word in missing:
                if self._example_repair_cancel.is_set():
                    return
                try:
                    found = enrich_entry(word, self.lookup_word)
                    updates[word['word']] = {'example': found['example'], 'translation': found.get('translation', '')}
                except Exception:
                    # Keep every existing word; retry is available in Settings.
                    pass
            events.put(updates)

        def poll():
            self._example_repair_job = None
            try:
                updates = events.get_nowait()
            except queue.Empty:
                self._example_repair_job = self.after(100, poll)
                return
            self._example_repair_busy = False
            if updates:
                try:
                    self.store.repair_examples(updates)
                except RuntimeError as error:
                    messagebox.showwarning('例句未保存', str(error), parent=self)
                else:
                    if self.session:
                        repair_example_data({'words': self.session.words,
                                             'active_session': {'history': self.session.history}}, updates)
                        if self.current_page == 'practice':
                            word = self.session.word()
                            self._full_example = word.get('example') or ''
                            revealed = self.session.current['kind'] == 'study' or bool(self.feedback)
                            self._set_example(self._full_example if revealed else mask_example(self._full_example, word['word']),
                                              word['word'] if revealed else None)
                            if revealed:
                                self.translation_label.configure(text=word.get('translation', ''))
            self._sync_example_health()

        threading.Thread(target=worker, daemon=True).start()
        self._example_repair_job = self.after(100, poll)

    def _sync_example_health(self):
        label = getattr(self, '_example_health_label', None)
        if label is not None and label.winfo_exists():
            count = sum(has_example(word) for word in self.store.words)
            suffix = ' · 正在补全缺失例句…' if self._example_repair_busy else ''
            label.configure(text=f'例句已补齐：{count} / {len(self.store.words)} 条' + suffix)

    def _apply_theme(self):
        self._stop_page_animation()
        self._page_cache.clear()
        self.colors = palette(self.store.settings["theme"])
        self.colors["glass"] = self.store.settings.get("glass_enabled", True)
        self.configure(bg=self.colors["bg"])
        self.attributes("-alpha", self.colors["window_alpha"])
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.Treeview", background=self.colors["surface"], fieldbackground=self.colors["surface"],
                        foreground=self.colors["text"], rowheight=46, borderwidth=0, font=ui_font(10))
        style.configure("App.Treeview.Heading", background=self.colors["surface_alt"], foreground=self.colors["muted"],
                        font=ui_font(9), relief="flat")
        style.map("App.Treeview", background=[("selected", self.colors["blue_light"])], foreground=[("selected", self.colors["text"])])
        style.configure("TEntry", padding=10, fieldbackground=self.colors["surface_alt"], foreground=self.colors["text"], insertcolor=self.colors["text"])
        style.configure("TCombobox", padding=8, fieldbackground=self.colors["surface_alt"], foreground=self.colors["text"],
                        background=self.colors["surface_alt"], bordercolor=self.colors["border"],
                        lightcolor=self.colors["border"], darkcolor=self.colors["border"], arrowcolor=self.colors["muted"])
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["surface_alt"])],
                  foreground=[("readonly", self.colors["text"])],
                  background=[("readonly", self.colors["surface_alt"]), ("active", self.colors["sidebar_hover"])],
                  arrowcolor=[("active", self.colors["text"])])
        style.configure("Vertical.TScrollbar", background=self.colors["surface_alt"],
                        troughcolor=self.colors["bg"], bordercolor=self.colors["bg"],
                        lightcolor=self.colors["surface_alt"], darkcolor=self.colors["surface_alt"],
                        arrowcolor=self.colors["muted"], relief="flat", borderwidth=0)
        style.map("Vertical.TScrollbar", background=[("active", self.colors["border"]),
                                                       ("pressed", self.colors["muted"])],
                  arrowcolor=[("active", self.colors["text"])])
        style.configure("Horizontal.TProgressbar", background=self.colors["green"], troughcolor=self.colors["border"], borderwidth=0, thickness=5)
        style.configure("TNotebook", background=self.colors["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 10), font=ui_font(10), background=self.colors["surface_alt"], foreground=self.colors["muted"])
        style.map("TNotebook.Tab", background=[("selected", self.colors["surface"])], foreground=[("selected", self.colors["text"])])
        if hasattr(self, "shell"):
            self.shell.destroy()
        self.shell = SceneFrame(self, self.colors)
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)
        sidebar_bg = self.colors["sidebar"]
        self.sidebar = SceneFrame(self.shell, self.colors, width=226)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(6, weight=1)
        self.nav = {}
        self.nav_icons = {}
        brand = SceneFrame(self.sidebar, self.colors)
        brand.grid(row=0, column=0, padx=16, pady=(18, 12), sticky="ew")
        self.brand_icon = ImageTk.PhotoImage(app_icon(31))
        tk.Label(brand, image=self.brand_icon, bg=sidebar_bg).pack(side="left", padx=(2, 9))
        brand_text = SceneFrame(brand, self.colors)
        brand_text.pack(side="left")
        tk.Label(brand_text, text="英语生词本", font=ui_font(11, True), fg=self.colors["text"], bg=sidebar_bg).pack(anchor="w")
        tk.Label(brand_text, text="本地学习空间", font=ui_font(8), fg=self.colors["muted"], bg=sidebar_bg).pack(anchor="w", pady=(1, 0))
        self.nav_icons["add"] = line_icon("add", self.colors["text"], 22)
        create = tk.Button(brand, image=self.nav_icons["add"], command=self.open_add_dialog,
                           bg=sidebar_bg, activebackground=self.colors["sidebar_hover"], relief="flat", bd=0,
                           padx=7, pady=7, cursor="hand2", takefocus=True)
        create.pack(side="right")
        ToolTip(create, "新增单词或固定搭配", background=self.colors["surface_alt"], foreground=self.colors["text"])
        tk.Label(self.sidebar, text="工作区", bg=sidebar_bg, fg=self.colors["muted"], font=ui_font(8)).grid(
            row=1, column=0, sticky="w", padx=20, pady=(5, 5))
        for i, (key, title, command) in enumerate((("home", "今日学习", self.show_home), ("words", "生词本", self.show_words),
                                                  ("essays", "作文资料", self.show_essays), ("progress", "学习足迹", self.show_progress)), 2):
            self.nav_icons[key] = line_icon(key, self.colors["muted"])
            button = NavigationButton(self.sidebar, self.colors, text=title, icon=self.nav_icons[key], command=command)
            button.grid(row=i, column=0, sticky="ew", padx=8, pady=2)
            self.nav[key] = button

        quick = SceneFrame(self.sidebar, self.colors)
        quick.grid(row=7, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.button(quick, "+ 添加单词 / 搭配", self.open_add_dialog, height=40).pack(fill="x")
        self.button(quick, "批量导入词表", self.open_import_dialog, height=36, secondary=True).pack(fill="x", pady=(6, 0))
        recent = SceneFrame(self.sidebar, self.colors)
        recent.grid(row=8, column=0, sticky="ew", padx=8, pady=(0, 8))
        tk.Label(recent, text="最近添加", bg=sidebar_bg, fg=self.colors["muted"], font=ui_font(9)).pack(anchor="w", padx=12, pady=(0, 4))
        for word in self.store.words[-3:][::-1]:
            tk.Button(recent, text=str(word.get("word", ""))[:24], command=lambda w=word: self.open_word_detail(w),
                      anchor="w", bg=sidebar_bg, fg=self.colors["muted"], activebackground=self.colors["sidebar_hover"],
                      activeforeground=self.colors["text"], relief="flat", bd=0, padx=12, pady=6,
                      font=english_font(9), cursor="hand2").pack(fill="x")

        self.nav_icons["settings"] = line_icon("settings", self.colors["muted"])
        settings_button = NavigationButton(self.sidebar, self.colors, text="设置", icon=self.nav_icons["settings"], command=self.show_settings)
        settings_button.grid(row=9, column=0, sticky="ew", padx=15, pady=2)
        ToolTip(settings_button, "设置", background=self.colors["surface_alt"], foreground=self.colors["text"])
        self.nav["settings"] = settings_button
        footer = SceneFrame(self.sidebar, self.colors)
        footer.grid(row=10, column=0, sticky="ew", padx=20, pady=(10, 18))
        tk.Label(footer, text="●", bg=sidebar_bg, fg=self.colors["green"], font=english_font(8)).pack(side="left")
        tk.Label(footer, text="  词库与进度保存在本机", bg=sidebar_bg, fg=self.colors["muted"], font=ui_font(8)).pack(side="left")
        self.page_host = SceneFrame(self.shell, self.colors)
        self.page_host.grid(row=0, column=1, sticky="nsew", padx=32, pady=26)
        self.page_frame = SceneFrame(self.page_host, self.colors)
        self.page_frame.place(x=0, y=0, relwidth=1, relheight=1)

    def label(self, parent, text, size=11, muted=False, english=False, emphasis=False, **kwargs):
        scene = parent
        while scene and not isinstance(scene, SceneFrame):
            scene = getattr(scene, "master", None)
        if scene and self.colors.get("glass", True) and self.colors["scene_start"] != self.colors["scene_end"]:
            return SceneLabel(parent, self.colors, text=text, foreground=self.colors["muted" if muted else "text"],
                              font=(english_font if english else ui_font)(size, emphasis), material=scene.material, **kwargs)
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.colors["muted" if muted else "text"],
                        font=(english_font if english else ui_font)(size, emphasis), **kwargs)

    def button(self, parent, text, command, width=170, height=46, secondary=False):
        return GradientRoundedButton(parent, text=text, command=command, width=width, height=height,
                                     start=self.colors["surface_alt"] if secondary else self.colors["button_start"],
                                     end=self.colors["blue_light"] if secondary else self.colors["button_end"],
                                     foreground=self.colors["text"] if secondary else "#ffffff", font=ui_font(11, True))

    def _stop_page_animation(self):
        if self._page_animation_job:
            self.after_cancel(self._page_animation_job)
            self._page_animation_job = None
        for widget, item, color in self._page_fade_items:
            if widget.winfo_exists():
                widget.itemconfigure(item, fill=color)
        self._page_fade_items = []
        if hasattr(self, "page_frame") and self.page_frame.winfo_exists():
            self.page_frame.place_configure(y=0)

    def _animate_page_in(self):
        if not self.page_frame.winfo_exists():
            return
        self._stop_page_animation()
        frame = self.page_frame

        def collect(widget):
            if isinstance(widget, (SceneLabel, WordCanvas, GradientRoundedButton)):
                for item in widget.find_all():
                    if widget.type(item) == "text":
                        color = widget.itemcget(item, "fill")
                        if len(color) == 7 and color.startswith("#"):
                            self._page_fade_items.append((widget, item, color))
            for child in widget.winfo_children():
                collect(child)

        collect(frame)
        started = time.perf_counter()
        self._refresh_scene(self.page_host)

        def step():
            if not frame.winfo_exists():
                return
            progress = min(1.0, (time.perf_counter() - started) / .24)
            eased = 1 - (1 - progress) ** 3
            frame.place_configure(y=round(12 * (1 - eased)))
            # Fade text over the application's own background; leave the window opaque.
            background = self.colors["bg"]
            for widget, item, color in self._page_fade_items:
                if widget.winfo_exists():
                    mixed = "#" + "".join(f"{round(int(background[i:i+2], 16) + (int(color[i:i+2], 16) - int(background[i:i+2], 16)) * eased):02x}" for i in (1, 3, 5))
                    widget.itemconfigure(item, fill=mixed)
            if progress < 1:
                self._page_animation_job = self.after(16, step)
            else:
                self._page_animation_job = None
                self._stop_page_animation()
                self._refresh_scene(self.page_host)

        step()

    def _refresh_scene(self, widget):
        if isinstance(widget, (SceneFrame, SceneLabel, GradientRoundedButton)):
            widget.schedule_paint()
        if isinstance(widget, RoundedCard):
            widget.schedule_paint()
        for child in widget.winfo_children():
            self._refresh_scene(child)

    def _page_token(self):
        return (id(self.session), self.session.completed_count if self.session else None)

    def _remember_page(self, key):
        self._page_cache[key] = {"frame": self.page_frame, "body": self.body,
                                 "data": deepcopy(self.store.data), "token": self._page_token(),
                                 "refs": self._page_refs(key)}

    def _page_refs(self, key):
        names = ("header_title",) + {"essays": ("essay_detail", "essay_notebook", "essay_footer", "_displayed_essay"),
                                    "words": ("_word_search", "_word_search_entry", "_word_tree", "_word_type_filter"),
                                    "settings": ("_settings_status", "_example_health_label")}.get(key, ())
        return {name: getattr(self, name) for name in names if hasattr(self, name)}

    def _hide_current_page(self):
        self._stop_word_audio()
        self._stop_page_animation()
        cached = next((entry for entry in self._page_cache.values() if entry["frame"] is self.page_frame), None)
        if cached:
            cached["refs"] = self._page_refs(self.current_page)
            self.page_frame.place_forget()
        else:
            self.page_frame.destroy()

    def _restore_page(self, key):
        cached = self._page_cache.get(key)
        if not cached or cached["data"] != self.store.data or cached["token"] != self._page_token():
            return False
        if self.page_frame is cached["frame"]:
            return True
        self._hide_current_page()
        self.page_frame, self.body = cached["frame"], cached["body"]
        for name, value in cached["refs"].items():
            setattr(self, name, value)
        self.current_page = key
        self.page_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self._update_nav(key)
        self._page_animation_job = self.after_idle(self._animate_page_in)
        return True

    def _update_nav(self, key):
        for name, button in self.nav.items():
            button.configure(selected=name == ("home" if key == "practice" else key))

    def _scroll_to_setting(self, panel, widget, buttons, selected):
        panel.update_idletasks()
        for index, button in enumerate(buttons):
            button.configure(bg=self.colors["surface_alt"] if index == selected else self.colors["bg"],
                             fg=self.colors["text"] if index == selected else self.colors["muted"])
        panel.scroll_to(widget.winfo_y())

    def _page(self, key, title, subtitle="", scroll=True):
        self._hide_current_page()
        stale = self._page_cache.pop(key, None)
        if stale:
            stale["frame"].destroy()
        self.page_frame = SceneFrame(self.page_host, self.colors)
        self.page_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.current_page = key
        self._update_nav(key)
        header = SceneFrame(self.page_frame, self.colors, height=46)
        header.pack_propagate(False)
        header.pack(fill="x", pady=(0, 22))
        self.header_title = self.label(header, title, 20, emphasis=True)
        self.header_title.place(x=0, y=2)
        if subtitle:
            self.label(header, subtitle, 9, muted=True).pack(side="right", pady=(7, 0))
        if scroll:
            panel = ScrollablePanel(self.page_frame, self.colors["bg"])
            panel.pack(fill="both", expand=True)
            self.body = panel.content
        else:
            self.body = SceneFrame(self.page_frame, self.colors)
            self.body.pack(fill="both", expand=True)
        self._page_animation_job = self.after_idle(self._animate_page_in)
        return self.body

    def _new_words(self):
        return [w for w in self.store.words if not w.get("last_review") and not int(w.get("total_reviews", 0))]

    def _due_words(self):
        today = date.today().isoformat()
        return sorted((w for w in self.store.words if (w.get("last_review") or int(w.get("total_reviews", 0)))
                       and w.get("next_review", today) <= today),
                      key=lambda w: w.get("next_review", ""))

    @cached_page("home")
    def show_home(self):
        body = self._page("home", "今天，也积累一点", date.today().strftime("%Y / %m / %d"))
        if self.session:
            resume = RoundedCard(body, self.colors, padding=18)
            resume.pack(fill="x", pady=(0, 18))
            copy = SceneFrame(resume.content, self.colors, material=True)
            copy.pack(side="left")
            self.label(copy, "继续上次的练习", 12, emphasis=True).pack(anchor="w")
            self.label(copy, f"已完成 {self.session.completed_count} / {len(self.session.words)} 条 · 进度已保留", 10, muted=True).pack(anchor="w", pady=(4, 0))
            self.button(resume.content, "继续练习  →", self.show_practice, width=150, height=42).pack(side="right")
        self.label(body, "今日安排", 12, emphasis=True).pack(anchor="w", pady=(0, 12))
        row = SceneFrame(body, self.colors)
        row.pack(fill="x", pady=(0, 20))
        for column, (title, english, words, mode, tip) in enumerate((("学习新词", "待学习", self._new_words(), "learn", "认识新词，放进真实语境"),
                                                                    ("到期复习", "今日待复习", self._due_words(), "review", "让记忆在恰当的时候回来"))):
            row.columnconfigure(column, weight=1, uniform="actions")
            card = RoundedCard(row, self.colors, padding=22)
            card.grid(row=0, column=column, sticky="ew", padx=(0, 10) if column == 0 else (10, 0))
            top = SceneFrame(card.content, self.colors, material=True)
            top.pack(fill="x")
            self.label(top, title, 17, emphasis=True).pack(side="left")
            self.label(top, str(len(words)), 27, english=True).pack(side="right")
            self.label(card.content, english, 10, muted=True).pack(anchor="w")
            self.label(card.content, tip, 10, muted=True).pack(anchor="w", pady=(9, 16))
            action = self.button(card.content, "已有练习进行中" if self.session else "开始学习  →" if mode == "learn" else "开始复习  →",
                                 lambda m=mode: self.start_session(m), secondary=mode == "learn" and bool(self._due_words()))
            action.pack(fill="x")
            if self.session or not words:
                action.configure(text="请先继续上次练习" if self.session else "暂无待学新词" if mode == "learn" else "今日复习已完成", state="disabled")
            self.label(card.content, f"每组最多 {self.store.settings['group_size']} 条 · 可在设置调整", 9, muted=True).pack(anchor="w", pady=(10, 0))
        featured = self.store.words[date.today().toordinal() % len(self.store.words)] if self.store.words else None
        WordCanvas(body, self.colors, title=featured["word"] if featured else "a little, every day",
                   subtitle=featured.get("meaning", "") if featured else "点击左侧「添加单词 / 搭配」，开始积累",
                   caption="今日搭配" if featured and item_type(featured) == "phrase" else "今日一词", height=210, landscape=True,
                   display_font=english_font(30, True), body_font=ui_font(11)).pack(fill="x", pady=(0, 16))
        phrases = sum(item_type(w) == "phrase" for w in self.store.words)
        self.label(body, f"生词本里有 {len(self.store.words) - phrases} 个单词、{phrases} 条固定搭配。按自己的节奏，一组一组来。", 9, muted=True).pack(anchor="w", pady=(0, 8))

    def start_session(self, mode):
        if self.session:
            self.show_practice()
            return
        words = self._new_words() if mode == "learn" else self._due_words()
        if not words:
            body = self._page("home", "学习" if mode == "learn" else "复习")
            self.label(body, "新词已经学完了" if mode == "learn" else "今天的复习已完成", 24, emphasis=True).pack(pady=(65, 20))
            self.label(body, "可以添加单词或搭配，也可以在生词本里选择内容再练习。", muted=True).pack()
            self.button(body, "回到今日", self.show_home).pack(pady=30)
            return
        self.session = PracticeSession(words[:int(self.store.settings["group_size"])], mode,
                                       self.store.settings[mode + "_spelling"])
        if self._checkpoint():
            self.show_practice()

    def _checkpoint(self):
        old = self.store.data.get("active_session")
        self.store.data["active_session"] = self.session.snapshot() if self.session else None
        try:
            self.store.save()
            return True
        except OSError as error:
            self.store.data["active_session"] = old
            messagebox.showerror("进度未保存", "无法保存练习进度，请检查磁盘或文件权限后重试。\n" + str(error), parent=self)
            return False

    def show_practice(self):
        if not self.session:
            self.show_home()
            return
        if self.session.finished:
            self._finish_session()
            return
        self.feedback = None
        self.entry = None
        self.choice_actions = []
        body = self._page("practice", "学习" if self.session.mode == "learn" else "复习",
                          f"本组 {len(self.session.words)} 条")
        progress = SceneFrame(body, self.colors)
        progress.pack(fill="x", pady=(0, 18))
        self.label(progress, f"{self.session.completed_count} / {len(self.session.words)} 条", 9, muted=True).pack(side="left", padx=(0, 16))
        ttk.Progressbar(progress, maximum=len(self.session.words), value=self.session.completed_count).pack(side="left", fill="x", expand=True)
        self.button(progress, "稍后继续", self.show_home, width=115, height=34, secondary=True).pack(side="right", padx=(18, 0))
        columns = SceneFrame(body, self.colors)
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=3, uniform="practice")
        columns.columnconfigure(1, weight=2, uniform="practice")
        main = SceneFrame(columns, self.colors)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        side = RoundedCard(columns, self.colors, padding=22)
        side.grid(row=0, column=1, sticky="new")
        w, kind = self.session.word(), self.session.current["kind"]
        visible_word = kind in ("recognize", "meaning", "study")
        title = w["word"] if visible_word else w["meaning"]
        subtitle = w.get("phonetic", "") if visible_word else "想一想对应的英文"
        self.question_canvas = WordCanvas(main, self.colors, title=title, subtitle=subtitle,
                    caption="固定搭配" if item_type(w) == "phrase" else "", height=224, display_font=english_font(28, True) if visible_word else ui_font(18, True), body_font=ui_font(11))
        self.question_canvas.pack(fill="x")
        soundrow = SceneFrame(main, self.colors)
        soundrow.pack(fill="x", pady=(10, 14))
        self.sound_icon = line_icon("sound", self.colors["blue"], 22)
        sound_button = tk.Button(soundrow, image=self.sound_icon, command=lambda: self.speech.speak(w["word"]),
                                 bd=0, bg=self.colors["bg"], activebackground=self.colors["sidebar_hover"],
                                 padx=8, pady=6, cursor="hand2", takefocus=True)
        sound_button.pack(side="left")
        ToolTip(sound_button, "听发音（空格）", background=self.colors["surface_alt"], foreground=self.colors["text"])
        if self.session.history:
            self.button(soundrow, "返回上一题", self.undo_answer, width=130, height=34, secondary=True).pack(side="right")
        self.actions = SceneFrame(main, self.colors)
        self.actions.pack(fill="x")
        self.context = side.content
        self.label(self.context, "在语境里记住它", 12, emphasis=True).pack(anchor="w", pady=(0, 14))
        self.context_text = tk.Text(self.context, height=5, bg=self.colors["surface"], fg=self.colors["text"],
                                    bd=0, wrap="word", font=english_font(12), highlightthickness=0)
        self.context_text.pack(fill="x")
        self._full_example = (w.get("example") or "").strip()
        example = self._full_example or "暂无例句，可在生词本中查看这个词。"
        if kind != "study":
            example = mask_example(example, w["word"])
        self._set_example(example, w["word"] if kind == "study" else None)
        self.translation_label = self.label(self.context, w.get("translation", "") if kind == "study" else "作答后展开释义与例句。",
                                            10, muted=True, justify="left", anchor="w", wraplength=270)
        self.translation_label.pack(fill="x", pady=(15, 10))
        self.meaning_label = self.label(self.context, (w.get("part_of_speech", "") + "  " + w["meaning"]) if kind == "study" else "",
                                       11, justify="left", anchor="w", wraplength=270)
        self.meaning_label.pack(fill="x", pady=(8, 8))
        self.usage_label = self.label(self.context, w.get("usage", "") if kind == "study" else "", 9, muted=True,
                                     justify="left", anchor="w", wraplength=270)
        self.usage_label.pack(fill="x")
        self.button(self.context, "播放例句", lambda: self.speech.speak(self._full_example), width=130, height=36, secondary=True).pack(anchor="w", pady=(20, 0))
        if kind == "study":
            self.button(self.actions, "记住了，继续  →", lambda: self._advance(True, 3)).pack(fill="x", pady=8)
            self.default_action = lambda: self._advance(True, 3)
        elif kind == "recognize" or (kind == "meaning" and len(self.session.current["choices"]) < 2):
            self.label(self.actions, "想起它的意思了吗？", muted=True).pack(anchor="w", pady=(0, 10))
            for i, (label, quality) in enumerate((("认识", 3), ("有点模糊", 2), ("忘记了", 1)), 1):
                action = lambda q=quality: self._show_feedback(q > 1, q)
                self.button(self.actions, f"{i}   {label}", action, secondary=i != 1).pack(fill="x", pady=4)
                self.choice_actions.append(action)
            self.default_action = None
        elif kind == "meaning":
            self.label(self.actions, "选出对应的意思", muted=True).pack(anchor="w", pady=(0, 8))
            for i, meaning in enumerate(self.session.current["choices"], 1):
                action = lambda v=meaning: self._show_feedback(v == w["meaning"], 3)
                self.button(self.actions, f"{i}   {meaning}", action, height=60, secondary=True).pack(fill="x", pady=4)
                self.choice_actions.append(action)
            self.button(self.actions, "想不起来", lambda: self._show_feedback(False, 1), height=35, secondary=True).pack(fill="x", pady=8)
            self.default_action = None
        else:
            self.label(self.actions, "输入保存的完整搭配，按 Enter 确认" if item_type(w) == "phrase" else "输入英文，按 Enter 确认", muted=True).pack(anchor="w", pady=(0, 12))
            self.answer_var = tk.StringVar()
            self.entry = ttk.Entry(self.actions, textvariable=self.answer_var, font=english_font(20))
            self.entry.pack(fill="x", pady=(0, 14))
            self.button(self.actions, "确认  →", self.check_typed).pack(fill="x", pady=4)
            self.button(self.actions, "想不起来", lambda: self._show_feedback(False, 1), secondary=True).pack(fill="x", pady=4)
            self.default_action = self.check_typed
            self.entry.focus_set()
        self.label(body, "自动读单词与例句 · 切题即停止上一条    |    Space 听发音 · Enter 继续 · 数字键选择", 8, muted=True).pack(anchor="w", pady=(20, 8))
        self._auto_read_word(w, self.page_frame)

    def _stop_word_audio(self, owner=None):
        if owner is not None and owner is not self._speech_owner:
            return
        if self._speech_job is not None:
            self.after_cancel(self._speech_job)
            self._speech_job = None
        self._speech_owner = None
        self.speech.stop()

    def _auto_read_word(self, word, owner):
        self._stop_word_audio()
        self._speech_owner = owner
        spoken_word, example = word["word"], word.get("example") or ""

        def play():
            self._speech_job = None
            if self._speech_owner is owner and owner.winfo_exists():
                self.speech.read_word(spoken_word, example)

        # Let the card paint first; rapid switches cancel any stale callback.
        self._speech_job = self.after_idle(play)

    def _set_example(self, example, target=None):
        self.context_text.configure(state="normal")
        self.context_text.delete("1.0", "end")
        self.context_text.insert("1.0", example)
        self.context_text.tag_configure("word", foreground=self.colors["blue"], font=english_font(12, True))
        if target:
            for match in expression_pattern(target).finditer(example):
                self.context_text.tag_add("word", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        self.context_text.configure(state="disabled")

    def check_typed(self):
        entered = re.sub(r"\s+", " ", self.answer_var.get().strip().casefold())
        if not entered:
            self.entry.focus_set()
            return
        self._show_feedback(answer_matches(entered, self.session.word()["word"]), 3)

    def _show_feedback(self, correct, quality):
        if self.feedback:
            return
        self.feedback = (correct, quality)
        w = self.session.word()
        self.entry = None
        for child in self.actions.winfo_children():
            child.destroy()
        self._set_example(self._full_example, w["word"])
        self.translation_label.configure(text=w.get("translation", ""))
        self.meaning_label.configure(text=w.get("part_of_speech", "") + "  " + w["meaning"])
        self.usage_label.configure(text=w.get("usage", ""))
        self.question_canvas.title = w["word"]
        self.question_canvas.subtitle = w.get("phonetic", "")
        self.question_canvas.display_font = english_font(28, True)
        self.question_canvas.paint()
        text = "记得很清楚" if correct and quality == 3 else "再巩固一下" if correct else "看看答案，稍后再遇见它"
        self.label(self.actions, text, 14, emphasis=True).pack(anchor="w", pady=(4, 8))
        self.label(self.actions, w["meaning"], 11, justify="left", wraplength=440).pack(anchor="w", pady=(0, 14))
        self.button(self.actions, "继续  →", lambda: self._advance(*self.feedback)).pack(fill="x", pady=4)
        if correct:
            self.button(self.actions, "其实记错了", self.mark_wrong, secondary=True, height=38).pack(fill="x", pady=4)
        self.choice_actions = []
        self.default_action = lambda: self._advance(*self.feedback)

    def mark_wrong(self):
        self.feedback = None
        self._show_feedback(False, 1)

    def _advance(self, correct, quality):
        self._stop_word_audio()
        before = self.session.snapshot()
        self.session.answer(correct, quality)
        if not self._checkpoint():
            self.session = PracticeSession.restore(before)
            self._auto_read_word(self.session.word(), self.page_frame)
            return
        self.show_practice()

    def undo_answer(self):
        self._stop_word_audio()
        before = self.session.snapshot()
        if self.session.undo():
            if not self._checkpoint():
                self.session = PracticeSession.restore(before)
            self.show_practice()

    def _finish_session(self):
        self._stop_word_audio()
        try:
            completed = self.store.commit_session(self.session)
        except OSError as error:
            body = self._page("practice", "这一组已完成")
            self.label(body, "进度尚未写入磁盘", 20).pack(pady=30)
            self.label(body, str(error), muted=True, wraplength=600).pack()
            self.button(body, "重试保存", self._finish_session).pack(pady=20)
            return
        self.finished_words = deepcopy(completed)
        self.session = None
        self.feedback = None
        self.default_action = None
        body = self._page("home", "这一组，记住了")
        hero = WordCanvas(body, self.colors, title="a little progress",
                          subtitle=f"完成 {len(completed)} 条 · 已安排下次复习", caption="做得不错，给记忆一点时间",
                          height=200, display_font=english_font(30, True), body_font=ui_font(11), landscape=True)
        hero.pack(fill="x", pady=(0, 18))
        card = RoundedCard(body, self.colors)
        card.pack(fill="x")
        self.label(card.content, "下次再遇见", 12, emphasis=True).pack(anchor="w", pady=(0, 10))
        for w in completed:
            row = tk.Frame(card.content, bg=self.colors["surface"])
            row.pack(fill="x", pady=7)
            self.label(row, w["word"], 13, english=True).pack(side="left")
            self.label(row, w["next_review"], 10, muted=True).pack(side="right")
        row = tk.Frame(body, bg=self.colors["bg"])
        row.pack(fill="x", pady=20)
        self.button(row, "回到今日", self.show_home, secondary=True).pack(side="left")
        self.button(row, "继续下一组  →", lambda: self.start_session("review" if self._due_words() else "learn")).pack(side="right")

    def show_review(self):
        self.show_home()

    @cached_page("words")
    def show_words(self):
        body = self._page("words", "我的生词本", f"{len(self.store.words)} 条内容", scroll=False)
        top = SceneFrame(body, self.colors)
        top.pack(fill="x", pady=(0, 12))
        search = self._word_search = tk.StringVar()
        self.label(top, "搜索英文 / 释义", 10, muted=True).pack(side="left", padx=(0, 12))
        self._word_search_entry = ttk.Entry(top, textvariable=search)
        self._word_search_entry.pack(side="left", fill="x", expand=True)
        self.button(top, "清空", lambda: search.set(""), width=65, height=40, secondary=True).pack(side="left", padx=(8, 0))
        self.button(top, "+ 添加", self.open_add_dialog, width=105).pack(side="right", padx=(16, 0))
        self.button(top, "批量导入", self.open_import_dialog, width=112, secondary=True).pack(side="right", padx=(12, 0))
        filters = SceneFrame(body, self.colors)
        filters.pack(fill="x", pady=(0, 14))
        type_filter = self._word_type_filter = tk.StringVar(value="全部内容")
        SegmentedChoice(filters, self.colors, options=[(v, v) for v in ("全部内容", "单词", "固定搭配")],
                        variable=type_filter).pack(side="left")
        self.label(filters, "Ctrl+F 搜索 · Esc 清空", 9, muted=True).pack(side="right")
        frame = tk.Frame(body, bg=self.colors["surface"])
        frame.pack(fill="both", expand=True)
        tree = self._word_tree = ttk.Treeview(frame, columns=("word", "type", "meaning", "next", "status"), show="headings", style="App.Treeview", selectmode="browse")
        for key, label, width in (("word", "单词 / 搭配", 180), ("type", "类型", 70), ("meaning", "释义", 200), ("next", "下次复习", 110), ("status", "状态", 90)):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=65, stretch=key in ("word", "meaning"))
        scrollbar = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        empty = tk.Label(frame, text="", font=ui_font(12), bg=self.colors["surface"], fg=self.colors["muted"], justify="center")
        footer = SceneFrame(body, self.colors)
        footer.pack(fill="x", pady=(12, 0))
        results = self.label(footer, "", 10, muted=True)
        results.pack(side="left")

        def open_selected(event=None):
            selected = tree.selection()
            word = next((w for w in self.store.words if selected and str(w["id"]) == selected[0]), None)
            if word:
                self.open_word_detail(word)
            return "break"

        details = self.button(footer, "查看详情  →", open_selected, width=140, height=40, secondary=True)
        details.pack(side="right")
        details.configure(state="disabled")
        tree.bind("<<TreeviewSelect>>", lambda e: details.configure(state="normal" if tree.selection() else "disabled"))
        def refresh(*args):
            selected = tree.selection()
            tree.delete(*tree.get_children())
            query = search.get().strip().casefold()
            new_ids = {w["id"] for w in self._new_words()}
            for w in self.store.words:
                entry_type = item_type(w)
                if type_filter.get() != "全部内容" and entry_type != {"单词": "word", "固定搭配": "phrase"}[type_filter.get()]:
                    continue
                if query and query not in (w["word"] + " " + w["meaning"]).casefold():
                    continue
                tree.insert("", "end", iid=str(w["id"]), values=(w["word"], "固定搭配" if entry_type == "phrase" else "单词", w["meaning"],
                            "学习后安排" if w["id"] in new_ids else w.get("next_review", ""),
                            "未学习" if w["id"] in new_ids else "已巩固" if w.get("level") == "mastered" else "巩固中"))
            count = len(tree.get_children())
            results.configure(text=f"显示 {count} / {len(self.store.words)} 条 · 选中后按 Enter 查看")
            if count:
                empty.place_forget()
                if selected and tree.exists(selected[0]):
                    tree.selection_set(selected[0])
            else:
                empty.configure(text="没有找到匹配的内容\n试试其他关键词，或清空搜索" if self.store.words else "生词本还是空的\n点击「添加」或「批量导入」开始积累")
                empty.place(relx=.5, rely=.5, anchor="center")
            details.configure(state="normal" if tree.selection() else "disabled")
        search.trace_add("write", refresh)
        type_filter.trace_add("write", refresh)
        refresh()
        tree.bind("<Double-1>", open_selected)
        tree.bind("<Return>", open_selected)

    @cached_page("progress")
    def show_progress(self):
        body = self._page("progress", "记忆的足迹", "当轮完成与长期巩固分开记录")
        today = date.today().isoformat()
        today_events = [e for e in self.store.data.get("reviews", []) if e.get("date") == today]
        row = SceneFrame(body, self.colors)
        row.pack(fill="x", pady=(0, 20))
        for i, (title, value) in enumerate((("今天完成", len({e["word_id"] for e in today_events})),
                                           ("待复习", len(self._due_words())), ("已巩固", sum(w.get("level") == "mastered" for w in self.store.words)))):
            row.columnconfigure(i, weight=1, uniform="stats")
            card = RoundedCard(row, self.colors)
            card.grid(row=0, column=i, sticky="ew", padx=(0, 15) if i < 2 else 0)
            self.label(card.content, title, muted=True).pack(anchor="w")
            self.label(card.content, str(value), 32, english=True).pack(anchor="w", pady=(10, 0))
        card = RoundedCard(body, self.colors)
        card.pack(fill="x")
        self.label(card.content, "最近的练习", 13, emphasis=True).pack(anchor="w", pady=(0, 12))
        events = self.store.data.get("reviews", [])[-15:][::-1]
        if not events:
            self.label(card.content, "从完成第一组开始，记录会出现在这里。", muted=True).pack(anchor="w")
        for event in events:
            quality = event.get("quality", 3 if event.get("known") else 1)
            self.label(card.content, f"{event.get('date', '')}    {event.get('word', '')}    " + {3: "记得清楚", 2: "有些模糊", 1: "继续巩固"}[quality], 10).pack(anchor="w", pady=6)
        self.label(body, "记得越稳，下次间隔越长；模糊或忘记的词会更早回来。", 9, muted=True).pack(anchor="w", pady=18)

    @cached_page("settings")
    def show_settings(self):
        body = self._page("settings", "设置", "外观、练习与本地数据", scroll=False)
        layout = SceneFrame(body, self.colors)
        layout.pack(fill="both", expand=True)
        layout.columnconfigure(0, weight=1)
        layout.rowconfigure(1, weight=1)

        categories = SceneFrame(layout, self.colors)
        categories.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        category_buttons = []
        for index, title in enumerate(("学习", "外观", "数据与版本")):
            category = tk.Button(categories, text=title, anchor="w", padx=12, pady=10,
                                 bg=self.colors["surface_alt"] if index == 0 else self.colors["bg"],
                                 fg=self.colors["text"] if index == 0 else self.colors["muted"],
                                 activebackground=self.colors["sidebar_hover"], activeforeground=self.colors["text"],
                                 relief="flat", bd=0, cursor="hand2", font=ui_font(11),
                                 highlightthickness=2, highlightcolor=self.colors["blue"], highlightbackground=self.colors["bg"])
            category.pack(side="left", padx=(0, 8))
            category_buttons.append(category)
        self._settings_status = self.label(categories, "更改后自动保存", 10, muted=True)
        self._settings_status.pack(side="right", padx=(12, 0))

        panel = ScrollablePanel(layout, self.colors["bg"])
        panel.grid(row=1, column=0, sticky="nsew")
        content = panel.content

        card = RoundedCard(content, self.colors, padding=22)
        card.pack(fill="x", pady=(0, 16))
        appearance_card = card
        self.label(card.content, "外观", 13, emphasis=True).pack(anchor="w")
        self.label(card.content, "选择应用整体的明暗与强调色。", 9, muted=True).pack(anchor="w", pady=(4, 16))
        row = SceneFrame(card.content, self.colors, material=True)
        row.pack(fill="x")
        SegmentedChoice(row, self.colors, options=(("codex", "深色"), ("mint", "薄荷浅色"), ("rose", "暖砂浅色")),
                        value=self.store.settings["theme"], command=self.change_theme).pack(fill="x")
        material = SceneFrame(card.content, self.colors, material=True)
        material.pack(fill="x", pady=(20, 0))
        description = SceneFrame(material, self.colors, material=True)
        description.pack(side="left")
        self.label(description, "透明渐变", 11, emphasis=True).pack(anchor="w")
        self.label(description, "卡片透出底层渐变色彩，文字保持清晰；关闭后使用实色背景。", 10, muted=True).pack(anchor="w", pady=(3, 0))
        glass = tk.BooleanVar(value=self.store.settings.get("glass_enabled", True))
        tk.Checkbutton(material, text="开启", variable=glass, command=lambda: self.change_glass(glass.get()),
                       bg=self.colors["surface"], fg=self.colors["text"], selectcolor=self.colors["surface_alt"],
                       activebackground=self.colors["surface"], activeforeground=self.colors["text"],
                       bd=0, highlightthickness=0, cursor="hand2", font=ui_font(10)).pack(side="right")

        card = RoundedCard(content, self.colors, padding=22)
        card.pack(fill="x", pady=(0, 16))
        learning_card = card
        self.label(card.content, "学习", 13, emphasis=True).pack(anchor="w")
        self.label(card.content, "这些设置会从下一组练习开始生效。", 9, muted=True).pack(anchor="w", pady=(4, 12))
        spelling_options = (("all", "全部单词"), ("errors", "只拼模糊或错词"), ("off", "关闭拼写"))
        rows = (("group_size", "每组条数", "每次最多安排多少条内容；完成一组后再开始下一组。", [(str(n), str(n) + " 条") for n in (5, 10, 20, 40)]),
                ("learn_spelling", "学习后的拼写", "选择新内容学完后的拼写范围。", spelling_options),
                ("review_spelling", "复习后的拼写", "选择复习结束后的拼写范围。", spelling_options))
        for index, (key, label, description, values) in enumerate(rows):
            if index:
                tk.Frame(card.content, height=1, bg=self.colors["border"]).pack(fill="x", pady=8)
            row = SceneFrame(card.content, self.colors, material=True)
            row.pack(fill="x", pady=7)
            copy = SceneFrame(row, self.colors, material=True)
            copy.pack(fill="x")
            self.label(copy, label, 11, emphasis=True).pack(anchor="w")
            self.label(copy, description, 10, muted=True).pack(anchor="w", pady=(3, 9))
            SegmentedChoice(row, self.colors, options=values, value=self.store.settings[key],
                            command=lambda value, k=key: self.save_setting(k, int(value) if k == "group_size" else value)).pack(fill="x")

        card = RoundedCard(content, self.colors, padding=22)
        card.pack(fill="x")
        data_card = card
        self.label(card.content, "数据与版本", 13, emphasis=True).pack(anchor="w")
        self.label(card.content, "所有生词、搭配、作文与学习进度都保存在这台电脑。", 9, muted=True).pack(anchor="w", pady=(5, 12))
        tk.Frame(card.content, height=1, bg=self.colors["border"]).pack(fill="x", pady=(0, 12))
        info = SceneFrame(card.content, self.colors, material=True)
        info.pack(fill="x")
        self.label(info, "拾词桌面版", 10).pack(side="left")
        self.label(info, self.version, 9, muted=True, english=True).pack(side="right")
        self.label(card.content, "支持离线练习与 Windows 语音；自动查词需要联网。", 8, muted=True).pack(anchor="w", pady=(12, 0))
        self._example_health_label = self.label(card.content, '', 10)
        self._example_health_label.pack(anchor='w', pady=(12, 6))
        self._sync_example_health()
        self.label(card.content, '当前词库：' + str(self.store.path.resolve()), 8, muted=True,
                   wraplength=600, justify='left').pack(anchor='w', pady=(0, 10))
        self.button(card.content, '补齐缺少的例句', self._fill_missing_examples, secondary=True, width=155, height=34).pack(anchor='w')
        cards = (learning_card, appearance_card, data_card)
        def select_category(index):
            previous = getattr(self, "_settings_category", 0)
            self._settings_category = index
            for card in cards:
                card.pack_forget()
            cards[index].pack(fill="x")
            for i, button in enumerate(category_buttons):
                selected = i == index
                button.configure(bg=self.colors["blue_light"] if selected else self.colors["bg"],
                                 fg=self.colors["blue"] if selected else self.colors["muted"],
                                 highlightbackground=self.colors["blue"] if selected else self.colors["bg"])
            panel.update_idletasks()
            panel.scroll_to(0)
            if index != previous:
                self._animate_page_in()
        for index, button in enumerate(category_buttons):
            button.configure(command=lambda i=index: select_category(i))
        select_category(getattr(self, "_settings_category", 0))

    def save_setting(self, key, value):
        old = self.store.settings[key]
        self.store.settings[key] = value
        try:
            self.store.save()
            status = getattr(self, "_settings_status", None)
            if self.current_page == "settings" and status is not None and status.winfo_exists():
                status.configure(text="已保存 · 下一组生效" if key in ("group_size", "learn_spelling", "review_spelling") else "已保存 · 已应用")
            return True
        except OSError as error:
            self.store.settings[key] = old
            messagebox.showerror("未能保存偏好", str(error), parent=self)
            self.show_settings()
            return False

    def change_theme(self, theme):
        if self.save_setting("theme", theme):
            self._apply_theme()
            self.show_settings()
            self._settings_status.configure(text="主题已保存 · 已应用")
            return True
        return False

    def change_glass(self, enabled):
        if self.save_setting("glass_enabled", bool(enabled)):
            self._apply_theme()
            self.show_settings()
            self._settings_status.configure(text="外观已保存 · 已应用")

    def open_word_detail(self, word):
        dialog = tk.Toplevel(self)
        dialog.title(word["word"])
        dialog.geometry("640x620")
        dialog.configure(bg=self.colors["bg"])
        dialog.transient(self)
        footer = tk.Frame(dialog, bg=self.colors["bg"])
        footer.pack(side="bottom", fill="x", padx=24, pady=18)
        self.button(footer, "练习这条搭配" if item_type(word) == "phrase" else "练习这个词", lambda: self._practice_word(word, dialog)).pack(side="right")
        self.button(footer, "关闭", dialog.destroy, secondary=True, width=110).pack(side="left")
        panel = ScrollablePanel(dialog, self.colors["bg"])
        panel.pack(fill="both", expand=True, padx=24, pady=20)
        WordCanvas(panel.content, self.colors, title=word["word"], subtitle=word.get("phonetic", ""),
                   caption="固定搭配" if item_type(word) == "phrase" else "", height=190,
                   display_font=english_font(29, True), body_font=ui_font(11)).pack(fill="x", pady=(0, 16))
        card = RoundedCard(panel.content, self.colors)
        card.pack(fill="x")
        for text, size, english in ((word.get("part_of_speech", "") + "  " + word["meaning"], 13, False),
                                     (word.get("example", ""), 13, True), (word.get("translation", ""), 10, False),
                                     (word.get("usage", ""), 10, False)):
            if text:
                self.label(card.content, text, size, english=english, justify="left", wraplength=500, anchor="w").pack(fill="x", pady=(0, 14))
        self.button(card.content, "听发音", lambda: self.speech.speak(word["word"]), secondary=True, width=120).pack(anchor="w")
        dialog.bind("<Destroy>", lambda event: self._stop_word_audio(dialog) if event.widget is dialog else None)
        self._auto_read_word(word, dialog)

    def _practice_word(self, word, dialog):
        dialog.destroy()
        if not self.session:
            mode = "learn" if word in self._new_words() else "review"
            self.session = PracticeSession([word], mode, self.store.settings[mode + "_spelling"])
            if not self._checkpoint():
                return
        self.show_practice()

    def _editing(self):
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox))

    def _focus_search(self, event=None):
        if self.focus_get() is not None and self.focus_get().winfo_toplevel() is not self:
            return
        if self.current_page == "words":
            self._word_search_entry.focus_set()
            self._word_search_entry.selection_range(0, "end")
            return "break"

    def _escape_key(self, event=None):
        if self.focus_get() is not None and self.focus_get().winfo_toplevel() is not self:
            return
        if self.current_page == "words":
            self._word_search.set("")
            return "break"

    def _return_key(self, event):
        if self.current_page == "practice" and self.default_action and (not self._editing() or self.focus_get() is self.entry):
            self.default_action()
            return "break"

    def _space_key(self, event):
        if self.current_page == "practice" and self.session and not self._editing():
            self.speech.speak(self.session.word()["word"])
            return "break"

    def _number_key(self, number):
        if self.current_page == "practice" and not self._editing() and number <= len(self.choice_actions):
            self.choice_actions[number - 1]()
            return "break"

    def _mousewheel(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        while widget:
            if isinstance(widget, ScrollablePanel):
                widget.scroll_by(-event.delta / 120 * 60)
                return "break"
            widget = getattr(widget, "master", None)

    def _close(self):
        self._example_repair_cancel.set()
        if self._example_repair_job is not None:
            self.after_cancel(self._example_repair_job)
            self._example_repair_job = None
        self._stop_word_audio()
        if self._page_animation_job:
            self.after_cancel(self._page_animation_job)
            self._page_animation_job = None
        self.speech.close()
        self.destroy()

    def open_import_dialog(self):
        return ImportDialog(self)

    def open_add_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("添加单词或固定搭配")
        dialog.geometry("680x700")
        dialog.minsize(620, 650)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=self.colors["surface"])

        header = tk.Frame(dialog, bg=self.colors["surface"])
        header.pack(fill="x", padx=28, pady=(24, 10))
        tk.Label(header, text="添加单词或固定搭配", bg=self.colors["surface"], fg=self.colors["text"], font=ui_font(16, emphasis=True)).pack(anchor="w")
        tk.Label(header, text="查询后仍可修改任何内容，再保存到生词本。", bg=self.colors["surface"], fg=self.colors["muted"], font=ui_font(9)).pack(anchor="w", pady=(3, 0))

        footer = tk.Frame(dialog, bg=self.colors["surface"])
        footer.pack(side="bottom", fill="x", padx=28, pady=20)
        form_panel = ScrollablePanel(dialog, self.colors["surface"])
        form_panel.pack(fill="both", expand=True, padx=28)
        form = form_panel.content
        word_var = tk.StringVar()
        phonetic_var = tk.StringVar()
        pos_var = tk.StringVar()
        type_var = tk.StringVar(value="自动识别")
        status_var = tk.StringVar(value="输入后按回车，或点击“自动查询”。")

        type_row = tk.Frame(form, bg=self.colors["surface"])
        type_row.pack(fill="x", pady=(4, 12))
        self.label(type_row, "内容类型", 9).pack(side="left")
        ttk.Combobox(type_row, textvariable=type_var, values=("自动识别", "单词", "固定搭配"), state="readonly", width=16).pack(side="right")
        tk.Label(form, text="英文单词或完整搭配", bg=self.colors["surface"], fg=self.colors["text"], font=ui_font(9)).pack(anchor="w", pady=(4, 5))
        query_row = tk.Frame(form, bg=self.colors["surface"])
        query_row.pack(fill="x")
        word_entry = ttk.Entry(query_row, textvariable=word_var)
        word_entry.pack(side="left", fill="x", expand=True)
        lookup_button = self.button(query_row, "自动查询", None, width=130)
        lookup_button.pack(side="left", padx=(10, 0))
        tk.Label(form, textvariable=status_var, bg=self.colors["surface"], fg=self.colors["muted"], font=ui_font(8)).pack(anchor="w", pady=(4, 10))
        self.label(form, "例如 pay attention to；sb. / sth. 等搭配占位词也可以保留。", 8, muted=True).pack(anchor="w", pady=(0, 12))

        split = tk.Frame(form, bg=self.colors["surface"])
        split.pack(fill="x")
        left = tk.Frame(split, bg=self.colors["surface"])
        right = tk.Frame(split, bg=self.colors["surface"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 6))
        right.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(left, text="音标", bg=self.colors["surface"], fg=self.colors["text"], font=ui_font(9)).pack(anchor="w", pady=(0, 5))
        ttk.Entry(left, textvariable=phonetic_var).pack(fill="x")
        tk.Label(right, text="词性", bg=self.colors["surface"], fg=self.colors["text"], font=ui_font(9)).pack(anchor="w", pady=(0, 5))
        ttk.Entry(right, textvariable=pos_var).pack(fill="x")

        text_widgets: dict[str, tk.Text] = {}
        fields = [
            ("meaning", "中文释义（必填）", 3),
            ("usage", "用法与搭配", 3),
            ("example", "英文例句（必填，保存时会尝试自动补全）", 3),
            ("translation", "例句翻译", 3),
        ]
        for key, label, height in fields:
            tk.Label(form, text=label, bg=self.colors["surface"], fg=self.colors["text"], font=ui_font(9)).pack(anchor="w", pady=(11, 5))
            widget = tk.Text(form, height=height, wrap="word", relief="solid", bd=1, highlightthickness=0, padx=8, pady=7, fg=self.colors["text"], bg=self.colors["surface_alt"], insertbackground=self.colors["blue"], selectbackground=self.colors["blue_light"], selectforeground=self.colors["text"], font=ui_font(9))
            widget.pack(fill="x")
            text_widgets[key] = widget

        self.button(footer, "取消", dialog.destroy, secondary=True, width=120).pack(side="right")
        save_button = self.button(footer, "保存", None, width=145)
        save_button.pack(side="right", padx=(0, 10))

        def set_text(key: str, value: str) -> None:
            widget = text_widgets[key]
            widget.delete("1.0", "end")
            widget.insert("1.0", value)

        def finish_lookup(result: dict | None, error: Exception | None) -> None:
            if not dialog.winfo_exists():
                return
            lookup_button.configure(state="normal", text="自动查询")
            save_button.configure(state="normal", text="保存")
            word_entry.configure(state="normal")
            if error:
                status_var.set(str(error))
                messagebox.showwarning("没有查到", str(error), parent=dialog)
                return
            if result:
                word_var.set(result["word"])
                phonetic_var.set(result["phonetic"])
                pos_var.set(result["part_of_speech"])
                for key in text_widgets:
                    set_text(key, result.get(key, ""))
                status_var.set("已自动补全。请确认内容后保存。" if has_example(result) else "已查到释义，但没有例句；请补充英文例句后保存。")

        def do_lookup(_event: object | None = None) -> None:
            word = word_var.get().strip()
            if not word:
                messagebox.showinfo("请输入内容", "请先输入英文单词或完整搭配。", parent=dialog)
                return
            lookup_button.configure(state="disabled", text="正在查询…")
            save_button.configure(state="disabled")
            word_entry.configure(state="disabled")
            status_var.set("正在查询这条内容的释义与例句…")

            def worker() -> None:
                try:
                    result = self.lookup_word(word)
                    self.after(0, lambda: finish_lookup(result, None))
                except Exception as error:  # UI boundary: show a friendly lookup error.
                    self.after(0, lambda error=error: finish_lookup(None, error))

            threading.Thread(target=worker, daemon=True).start()

        def finish_save(payload, error=None) -> None:
            if not dialog.winfo_exists():
                return
            save_button.configure(state="normal", text="保存")
            lookup_button.configure(state="normal")
            word_entry.configure(state="normal")
            if error:
                status_var.set("未保存：请补充英文例句后重试。")
                messagebox.showwarning("需要例句", str(error), parent=dialog)
                return
            set_text("example", payload.get("example", ""))
            set_text("translation", payload.get("translation", ""))
            try:
                created = self.store.add_word(payload)
            except (ValueError, OSError) as problem:
                messagebox.showwarning("无法保存", str(problem), parent=dialog)
                return
            dialog.destroy()
            messagebox.showinfo("已添加", f"{created['word']} 已加入生词本，可以从“学习”开始。", parent=self)
            if self.current_page == "words":
                self.show_words()
            elif self.current_page == "progress":
                self.show_progress()
            else:
                self.show_home()

        def save_word() -> None:
            payload = {
                "word": word_var.get().strip(),
                "entry_type": {"单词": "word", "固定搭配": "phrase"}.get(type_var.get(), "auto"),
                "phonetic": phonetic_var.get().strip(),
                "part_of_speech": pos_var.get().strip(),
                **{key: widget.get("1.0", "end").strip() for key, widget in text_widgets.items()},
            }
            if not payload["word"] or not payload["meaning"]:
                messagebox.showwarning("内容不完整", "英文内容和中文释义不能为空。", parent=dialog)
                return
            payload = complete_example(payload)
            if has_example(payload):
                finish_save(payload)
                return
            save_button.configure(state="disabled", text="补全例句…")
            lookup_button.configure(state="disabled")
            word_entry.configure(state="disabled")
            status_var.set("正在自动查询例句，完成后保存；也可以取消后自行填写例句。")

            def worker():
                try:
                    enriched = enrich_entry(payload, self.lookup_word)
                    self.after(0, lambda: finish_save(enriched))
                except Exception as problem:
                    self.after(0, lambda problem=problem: finish_save(payload, problem))

            threading.Thread(target=worker, daemon=True).start()

        lookup_button.configure(command=do_lookup)
        word_entry.bind("<Return>", do_lookup)
        save_button.configure(command=save_word)
        word_entry.focus_set()
