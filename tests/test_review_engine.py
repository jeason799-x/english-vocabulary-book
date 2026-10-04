import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
from datetime import date
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from review_engine import PracticeSession, plan_review
loader = importlib.machinery.SourceFileLoader("desktop_app", str(ROOT / "desktop_app.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)

WORDS = [{"id": i, "word": w, "meaning": m} for i, w, m in ((1, "apple", "苹果"), (2, "orange", "橙子"), (3, "pear", "梨"))]


class ReviewTests(unittest.TestCase):
    def finish(self, session):
        for _ in range(150):
            if session.finished:
                return
            session.answer(True)
        self.fail("Session failed to finish")

    def test_queue_interleaves_and_hides_no_stage_in_data(self):
        for seed in range(20):
            s = PracticeSession(WORDS, "review", "off", seed)
            pairs = []
            while not s.finished:
                pairs.append((s.current["word_id"], s.current["kind"]))
                alternatives = any(q["word_id"] != s.current["word_id"] for q in s.queue)
                last = s.current["word_id"]
                if s.current["kind"] == "meaning":
                    self.assertIn(s.word()["meaning"], s.current["choices"])
                    self.assertTrue(all(v in [w["meaning"] for w in WORDS] for v in s.current["choices"]))
                s.answer(True)
                if alternatives:
                    self.assertNotEqual(last, s.current["word_id"])
            self.assertEqual(9, len(pairs))

    def test_wrong_answer_returns_and_rating_survives_relearning(self):
        s = PracticeSession(WORDS, "review", "errors", 4)
        failed = dict(s.current)
        s.answer(False)
        self.assertIn({"word_id": failed["word_id"], "kind": failed["kind"]}, s.queue)
        self.finish(s)
        state = s.states[str(failed["word_id"])]
        self.assertEqual(1, state["quality"])
        self.assertEqual(1, state["errors"])
        self.assertIn("spelling", state["solved"])
        for key, state in s.states.items():
            if key != str(failed["word_id"]):
                self.assertNotIn("spelling", state["required"])

    def test_checkpoint_and_undo_restore_exact_question(self):
        s = PracticeSession(WORDS, "learn", "all", 9)
        before = s.snapshot()
        s.answer(True)
        restored = PracticeSession.restore(json.loads(json.dumps(s.snapshot())))
        self.assertTrue(restored.undo())
        self.assertEqual(before, restored.snapshot())
        self.finish(restored)
        self.assertTrue(all(state["introduced"] for state in restored.states.values()))
        self.assertTrue(all("spelling" in state["solved"] for state in restored.states.values()))

    def test_schedule_grows_and_forgetting_resets(self):
        word = {}
        intervals = []
        for _ in range(5):
            word.update(plan_review(word, 3, date(2026, 9, 30)))
            intervals.append(word["interval_days"])
        self.assertTrue(all(a < b for a, b in zip(intervals, intervals[1:])))
        self.assertEqual(1, plan_review(word, 1)["interval_days"])
        self.assertLess(plan_review(word, 2)["interval_days"], word["interval_days"])
        self.assertLessEqual(plan_review({"interval_days": 120}, 3)["interval_days"], 120)

    def test_commit_once_and_save_failure_preserves_data(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / "vocabulary.json")
            s = PracticeSession(store.words, "review", "off", 1)
            self.finish(s)
            original = json.dumps(store.data, sort_keys=True)
            original_save = store.save
            def fail():
                raise OSError("disk full")
            store.save = fail
            with self.assertRaises(OSError):
                store.commit_session(s)
            self.assertEqual(original, json.dumps(store.data, sort_keys=True))
            store.save = original_save
            store.commit_session(s)
            count = len(store.data["reviews"])
            store.commit_session(s)
            self.assertEqual(count, len(store.data["reviews"]))
            self.assertEqual(3, len([e for e in store.data["reviews"] if e.get("session_id") == s.id]))
            reopened = app.DataStore(store.path)
            self.assertEqual(store.data, reopened.data)

    def test_existing_and_corrupt_files_preserved(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "vocabulary.json"
            path.write_text(json.dumps({"words": WORDS, "reviews": [], "next_id": 4}), encoding="utf-8")
            store = app.DataStore(path)
            self.assertEqual(WORDS, [{key: value for key, value in word.items() if key not in ('example', 'translation')}
                                     for word in store.words])
            self.assertTrue(all(word.get('example') for word in store.words))
            path.write_text("{bad data", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                app.DataStore(path)
            self.assertEqual("{bad data", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
