"""Exercise visible choices, search and keyboard actions with disposable data."""
from pathlib import Path
import importlib.machinery
import importlib.util
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from tkinter import messagebox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("desktop_app", str(ROOT / "desktop_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
from ui_components import SegmentedChoice, GradientRoundedButton
from review_engine import PracticeSession


class SilentSpeech:
    def start(self): pass
    def close(self): pass
    def stop(self): pass
    def speak(self, text): return True
    def read_word(self, word, example=""): return True


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def pump(window):
    window.update_idletasks()
    window.after(120, window.quit)
    window.mainloop()
    window.update_idletasks()


with TemporaryDirectory() as directory:
    store = module.DataStore(Path(directory) / "vocabulary.json")
    store.add_word({"word": "pay attention to", "meaning": "注意",
                    "example": "Please pay attention to the details.", "translation": "请注意细节。"})
    store.words[0].update(last_review="2000-01-01", total_reviews=2, next_review="2000-01-02")
    window = module.VocabularyApp(store=store, speech=SilentSpeech())
    window.title("拾词 UI 预览 · 示例词库")
    if "--preview" in sys.argv:
        window.mainloop()
        raise SystemExit()
    errors = []
    window.report_callback_exception = lambda kind, error, tb: errors.append(repr(error))
    for theme in ("codex", "mint", "rose"):
        store.settings["theme"] = theme
        window._apply_theme()
        for size in ("1040x700", "1260x820"):
            window.geometry(size)
            window.show_home()
            pump(window)
            for w in descendants(window.body):
                if isinstance(w, GradientRoundedButton) and w.label.startswith("开始"):
                    assert w.winfo_rooty() + w.winfo_height() <= window.winfo_rooty() + window.winfo_height()
            window.show_words()
            pump(window)
            window._word_search.set("注意")
            assert len(window._word_tree.get_children()) == 1
            window._word_search.set("no match found")
            assert not window._word_tree.get_children()
            window._escape_key()
            assert len(window._word_tree.get_children()) == len(store.words)
            window._word_type_filter.set("固定搭配")
            assert len(window._word_tree.get_children()) == 1
            window.show_home()
            window.show_words()
            assert window._word_type_filter.get() == "固定搭配"
            selected = window._word_tree.get_children()[0]
            window._word_tree.selection_set(selected)
            with patch.object(window, "open_word_detail") as detail:
                window._word_tree.event_generate("<Return>")
                # Native keyboard delivery is tested after explicitly focusing the list.
                window._word_tree.focus_force()
                pump(window)
                window._word_tree.event_generate("<Return>")
                window.update()
                assert detail.called
            window.show_settings()
            pump(window)
            if window._settings_category != 0:
                next(w for w in descendants(window.body) if w.winfo_class() == "Button" and w.cget("text") == "学习").invoke()
                pump(window)
            choices = [w for w in descendants(window.body) if isinstance(w, SegmentedChoice) and w.winfo_ismapped()]
            group = next(w for w in choices if w.buttons[0][0] == "5")
            group.select("10")
            group.select("20")
            assert store.settings["group_size"] == 20
            status = window._settings_status
            text = status.itemcget(status.text_item, "text") if hasattr(status, "text_item") else status.cget("text")
            assert "下一组生效" in text
            with patch.object(store, "save", side_effect=OSError("test failure")), patch.object(messagebox, "showerror"):
                group.select("40")
                assert store.settings["group_size"] == 20
            pump(window)
            for w in descendants(window.body):
                if isinstance(w, SegmentedChoice) and w.winfo_ismapped():
                    for _, button in w.buttons:
                        assert button.winfo_width() >= button.winfo_reqwidth() - 2, (theme, size, button.label)
            appearance = next(w for w in descendants(window.body) if w.winfo_class() == "Button" and w.cget("text") == "外观")
            appearance.invoke()
            pump(window)
            window.change_glass(False)
            pump(window)
            assert store.settings["glass_enabled"] is False
            window.change_glass(True)
            pump(window)
    window.session = PracticeSession(store.words[:2], "learn", "all")
    window.show_home()
    pump(window)
    buttons = [(w.label, w.winfo_ismapped(), w.winfo_geometry()) for w in descendants(window.body) if isinstance(w, GradientRoundedButton)]
    assert any(text == "继续练习  →" and mapped for text, mapped, geometry in buttons), buttons
    assert not errors, errors
    window._close()
    print("UI checks passed: 3 themes, 2 sizes, search/filter/cache, Enter details, saved choices, save failure rollback, appearance and resume.")
