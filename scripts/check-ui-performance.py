"""Measure navigation and event-loop stalls using disposable study data."""
from pathlib import Path
import importlib.machinery
import importlib.util
import json
import statistics
import sys
import time
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("desktop_app", str(ROOT / "desktop_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
from essay_library import SAMPLE_ESSAY
from review_engine import PracticeSession


class SilentSpeech:
    def start(self): pass
    def close(self): pass
    def speak(self, _text): return True
    def stop(self): pass
    def read_word(self, word, example=""): return True


def pump(window, seconds):
    window.after(round(seconds * 1000), window.quit)
    window.mainloop()


with TemporaryDirectory() as directory:
    store = module.DataStore(Path(directory) / "vocabulary.json")
    store.add_many([{"word": f"sampleword{i}", "meaning": f"示例释义 {i}",
                     "example": f"This is sampleword{i} in a sentence."} for i in range(120)])
    store.save_essay(SAMPLE_ESSAY)
    window = module.VocabularyApp(store=store, speech=SilentSpeech())
    window.geometry("1120x760+30+30")
    errors = []
    window.report_callback_exception = lambda kind, error, traceback: errors.append(repr(error))
    pump(window, .3)
    results = []
    for _ in range(3):
        for method in (window.show_home, window.show_settings, window.show_words, window.show_essays, window.show_progress):
            samples = []
            previous = [time.perf_counter()]
            def pulse():
                now = time.perf_counter()
                samples.append((now - previous[0]) * 1000)
                previous[0] = now
                window._perf_pulse = window.after(8, pulse)
            pulse()
            started = time.perf_counter()
            method()
            window.update_idletasks()
            ready = (time.perf_counter() - started) * 1000
            samples.clear()
            previous[0] = time.perf_counter()
            widths = []
            page = window.page_frame
            binding = page.bind("<Configure>", lambda event: widths.append(event.width), add="+")
            pump(window, .24)
            page.unbind("<Configure>", binding)
            window.after_cancel(window._perf_pulse)
            assert len(set(widths)) <= 1, (method.__name__, widths)
            results.append({"page": method.__name__, "ready_ms": round(ready, 2),
                            "max_event_gap_ms": round(max(samples), 2)})
    # Cached views preserve search and scrolling, but a data change invalidates them.
    window.show_home()
    home = window.page_frame
    window.show_settings()
    window.update_idletasks()
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    categories = [w for w in descendants(window.body) if w.winfo_class() == "Button" and w.cget("text") == "数据与版本"]
    categories[0].invoke()
    pump(window, .18)
    window.show_home()
    assert window.page_frame is home
    window.show_essays()
    for index in range(4):
        window.essay_notebook.select(index)
        pump(window, .1)
    assert window.essay_notebook.nametowidget(window.essay_notebook.tabs()[3]).winfo_children()
    window.show_home()
    store.add_many([{"word": "freshlyadded", "meaning": "缓存更新检查", "example": "This is a freshlyadded test entry."}])
    window.show_home()
    assert window.page_frame is not home
    # Rapid navigation, interrupted scrolling, feedback, and live resizing.
    for _ in range(5):
        window.show_settings()
        window.update_idletasks()
        window.show_words()
        window.show_home()
        window.update_idletasks()
    window.session = PracticeSession(store.words[:5], "learn", "all")
    window.show_practice()
    pump(window, .2)
    for size in ("1040x700", "1260x820", "1120x760"):
        window.geometry(size)
        pump(window, .08)
    window._show_feedback(True, 3)
    pump(window, .2)
    window.destroy()
    assert not errors, errors
    summary = {}
    for name in sorted({row["page"] for row in results}):
        rows = [row for row in results if row["page"] == name]
        summary[name] = {"first_ready_ms": rows[0]["ready_ms"],
                         "warm_median_ready_ms": round(statistics.median(row["ready_ms"] for row in rows[1:]), 2),
                         "max_transition_event_gap_ms": max(row["max_event_gap_ms"] for row in rows)}
    print(json.dumps({"pages": summary, "callback_errors": errors}, ensure_ascii=False, indent=2))
