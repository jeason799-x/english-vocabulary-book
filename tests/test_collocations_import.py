from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vocabulary_items import normalize_expression, item_type, answer_matches, mask_example
from bulk_import import parse_import, decode_import, split_duplicates
from test_review_engine import app
from review_engine import PracticeSession


class CollocationImportTests(unittest.TestCase):
    def test_phrase_classification_and_full_answer(self):
        self.assertEqual("phrase", item_type({"word": "pay attention to"}))
        self.assertEqual("phrase", item_type({"word": "pay attention to", "entry_type": "auto"}))
        self.assertEqual("word", item_type({"word": "nonetheless"}))
        self.assertTrue(answer_matches("  PAY   attention to  ", "pay attention to"))
        self.assertFalse(answer_matches("pay attention", "pay attention to"))
        self.assertFalse(answer_matches("pay to attention", "pay attention to"))
        self.assertTrue(answer_matches("one’s own", "one's own"))
        self.assertTrue(answer_matches("prevent sb from doing sth", "prevent sb. from doing sth."))

    def test_phrase_hints_hide_inflected_expression(self):
        self.assertEqual("She ______ music.", mask_example("She is interested in music.", "be interested in"))
        self.assertEqual("She ______ her brother.", mask_example("She takes care of her brother.", "take care of"))
        self.assertEqual("Please ______ this.", mask_example("Please pay  attention to this.", "pay attention to"))
        self.assertEqual("We ______ each other.", mask_example("We depend on each other.", "depend on"))
        self.assertEqual("careful", mask_example("careful", "care"))

    def test_pasted_plain_and_excel_rows(self):
        records, errors = parse_import("apple 苹果\npay attention to 注意\n- take care of 照顾\nnonetheless\n中文提示")
        self.assertEqual(4, len(records))
        self.assertEqual(1, len(errors))
        self.assertEqual("pay attention to", records[1]["word"])
        self.assertEqual("phrase", records[1]["entry_type"])
        self.assertEqual("", records[3]["meaning"])
        records, errors = parse_import("英文\t中文释义\t类型\napple\t苹果\t单词\nbe interested in\t对……感兴趣\t固定搭配")
        self.assertEqual(2, len(records))
        self.assertFalse(errors)

    def test_csv_quoting_bom_and_gb_encoding(self):
        text = '\ufeffword,meaning,example,translation\n"take care of","照顾；照料","She takes care of him, every day.",她每天照顾他。\n'
        records, errors = parse_import(text)
        self.assertEqual("She takes care of him, every day.", records[0]["example"])
        self.assertFalse(errors)
        self.assertEqual("苹果", decode_import("苹果".encode("gb18030")))
        self.assertEqual("苹果", decode_import("苹果".encode("utf-8-sig")))

    def test_duplicate_normalization(self):
        records, errors = parse_import("PAY attention to 注意\npay  attention to 注意\napple 苹果")
        unique, count = split_duplicates(records, [{"word": "pay attention to"}])
        self.assertEqual(2, count)
        self.assertEqual("apple", unique[0]["word"])

    def test_bulk_atomic_save_no_progress_changes_and_phrase_session(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / "vocabulary.json")
            old_words = json.dumps(store.words, sort_keys=True)
            records, _ = parse_import("pay attention to 注意\ntake care of 照顾\napple 苹果\napple 苹果")
            original = json.dumps(store.data, sort_keys=True)
            with patch.object(store, "save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.add_many(records)
            self.assertEqual(original, json.dumps(store.data, sort_keys=True))
            with patch.object(store, "save", wraps=store.save) as save:
                added, duplicates = store.add_many(records)
                self.assertEqual(1, save.call_count)
            self.assertEqual(3, len(added))
            self.assertEqual(1, duplicates)
            self.assertEqual(old_words, json.dumps(store.words[:3], sort_keys=True))
            self.assertEqual("phrase", added[0]["entry_type"])
            session = PracticeSession(added, "learn", "all", 4)
            session.answer(True)
            restored = PracticeSession.restore(json.loads(json.dumps(session.snapshot())))
            for _ in range(100):
                if restored.finished:
                    break
                restored.answer(True)
            self.assertTrue(restored.finished)
            store.commit_session(restored)
            reopened = app.DataStore(store.path)
            self.assertEqual("phrase", reopened.words[-3]["entry_type"])
            self.assertEqual(1, reopened.words[-3]["total_reviews"])

    def test_phrase_lookup_uses_whole_expression(self):
        with patch.object(app, "lookup_youdao", return_value={"meaning": "注意", "example": "Pay attention to this."}) as lookup:
            with patch.object(app, "lookup_dictionary", side_effect=AssertionError("Single-word dictionary should not split a phrase")):
                found = app.lookup_word(" PAY   attention to ")
                lookup.assert_called_once_with("pay attention to")
                self.assertEqual("phrase", found["entry_type"])
                self.assertEqual("注意", found["meaning"])


if __name__ == "__main__":
    unittest.main()
