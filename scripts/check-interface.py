"""Inspect actual widget layouts using disposable study data."""
from pathlib import Path
import sys
import importlib.machinery
import importlib.util
import time
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("desktop_app", str(ROOT / "desktop_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
from review_engine import PracticeSession
from ui_components import FONT_FAMILIES
from essay_library import SAMPLE_ESSAY

class SilentSpeech:
    def start(self): pass
    def close(self): pass
    def speak(self, text): return True
    def stop(self): pass
    def read_word(self, word, example=""): return True

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

with TemporaryDirectory() as directory:
    store = module.DataStore(Path(directory) / "vocabulary.json")
    store.save_essay(SAMPLE_ESSAY)
    store.add_many([
        {"word": "pay attention to", "meaning": "注意", "example": "Please pay attention to this.", "translation": "请注意这一点。"},
        {"word": "take care of", "meaning": "照顾", "example": "She takes care of her brother.", "translation": "她照顾她的弟弟。"},
        {"word": "be interested in learning about other cultures", "meaning": "对了解其他文化感兴趣",
         "example": "She is interested in learning about other cultures.", "translation": "她对了解其他文化感兴趣。"},
    ])
    # Ensure both new and existing words are exercised without touching user data.
    for w in store.words:
        w["last_review"] = None
        w["total_reviews"] = 0
    window = module.VocabularyApp(store=store, speech=SilentSpeech())
    assert FONT_FAMILIES["body"] in ("Noto Sans SC", "Segoe UI Variable Text", "Microsoft YaHei UI", "ChillRoundF"), FONT_FAMILIES
    assert window.tk.call("font", "actual", window.option_get("font", "Font"), "-family") == FONT_FAMILIES["body"]
    print("Chinese UI font selected:", FONT_FAMILIES["body"], flush=True)
    if "--preview" in sys.argv:
        # Visual QA with a disposable session and no changes to real study records.
        window.session = PracticeSession(store.words, "review", "all", 4)
        window.show_practice()
        window.mainloop()
        raise SystemExit()
    errors = []
    window.report_callback_exception = lambda kind, error, traceback: errors.append(repr(error))
    for theme in ("codex", "mint", "rose"):
        store.settings["theme"] = theme
        window._apply_theme()
        for size in ("1240x800", "1000x680"):
            window.geometry(size)
            for method in (window.show_home, window.show_words, window.show_essays, window.show_progress, window.show_settings):
                method()
                window.update()
                assert window.page_frame.winfo_width() > 700
            window.show_essays()
            window.update()
            assert window.essay_detail.winfo_width() > 450
            assert window.essay_footer.winfo_y() + window.essay_footer.winfo_height() <= window.essay_detail.winfo_height()
            for index in range(4):
                window.essay_notebook.select(index)
                window.update()
            editor = window.open_essay_editor(store.essays[0])
            window.update()
            for index in range(5):
                editor.notebook.select(index)
                window.update()
            editor.variables['title'].set('临时作文标题')
            editor.save()
            window.update()
            assert store.essays[0]['title'] == '临时作文标题'
            paste_dialog = window.open_essay_paste()
            window.update()
            window.after(80, window.quit)
            window.mainloop()
            assert paste_dialog.text.winfo_height() > 200, (theme, size, paste_dialog.winfo_geometry(), paste_dialog.text.winfo_height())
            paste_dialog.text.insert('1.0', 'Essay_02\nAn original essay.\n**中文翻译：**\n一篇作文。\n**写作思路：**\n提出观点。\n**固定搭配：**\ntake notes | 记笔记 | 学习话题')
            preview = paste_dialog.prepare()
            window.update()
            assert preview.fields['translation'].get('1.0', 'end-1c') == '一篇作文。'
            preview.save()
            window.update()
            assert any(essay['code'] == 'Essay_02' for essay in store.essays)
            store.delete_essay(next(essay['id'] for essay in store.essays if essay['code'] == 'Essay_02'))
            window.start_session("learn")
            for _ in range(120):
                window.update()
                if window.session is None:
                    break
                if window.session.current["kind"] == "study":
                    window._advance(True, 3)
                else:
                    window._show_feedback(True, 3)
                    window.update()
                    window._advance(True, 3)
            assert window.session is None
            for w in store.words:
                w["next_review"] = "2000-01-01"
            window.start_session("review")
            window.update()
            window._show_feedback(False, 1)
            window.update()
            window._advance(False, 1)
            window.undo_answer()
            window.update()
            window.session = None
            window.store.data["active_session"] = None
            window.show_home()
            window.open_word_detail(store.words[0])
            window.update()
            for child in window.winfo_children():
                if child.winfo_class() == "Toplevel": child.destroy()
            window.open_add_dialog()
            window.update()
            for child in window.winfo_children():
                if child.winfo_class() == "Toplevel": child.destroy()
            window.show_words()
            importer = window.open_import_dialog()
            importer.text.insert("1.0", "new expression 新搭配\npay attention to 重复\nnewword\nmissingphrase")
            importer.text.edit_modified(False)
            importer.prepare()
            window.update()
            assert len(importer.records) == 3 and importer.duplicates == 1
            def fake_lookup(text):
                if text == "missingphrase": raise LookupError("not found")
                return {"word": text, "meaning": "新词释义", "example": f"We use {text} in this test."}
            importer.owner.lookup_word = fake_lookup
            importer.import_records()
            for _ in range(300):
                window.update()
                if not importer.busy: break
                time.sleep(.01)
            assert not importer.busy
            assert any(w["word"] == "new expression" for w in store.words)
            assert any(w["word"] == "newword" for w in store.words)
            assert not any(w["word"] == "missingphrase" for w in store.words)
            assert importer.import_button.state == "disabled"
            importer.close()
            # Each layout iteration starts from the same disposable vocabulary.
            store.data["words"] = store.words[:6]
            for w in store.words:
                w["last_review"] = None
                w["total_reviews"] = 0
    assert not errors, errors
    window.destroy()
    print("Interface checks passed: three themes, two sizes, mixed word/phrase sessions, long collocations, import preview and partial lookup failure.")
