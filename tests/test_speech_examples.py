import base64
import importlib.util
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from test_review_engine import app
from example_bank import complete_example, enrich_entry, has_example, repair_example_data

fill_spec = importlib.util.spec_from_file_location('fill_examples', Path(__file__).resolve().parents[1] / 'scripts' / 'complete-existing-examples.py')
fill_module = importlib.util.module_from_spec(fill_spec)
fill_spec.loader.exec_module(fill_module)


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.speech = app.SpeechService()
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.stdin = io.StringIO()
        self.speech.process = self.process

    def requests(self):
        return [json.loads(base64.b64decode(line).decode('utf-8'))
                for line in self.process.stdin.getvalue().splitlines()]

    def test_card_order_and_revisits_bypass_cooldown(self):
        for word in ('apple', 'pear', 'apple'):
            self.assertTrue(self.speech.read_word(word, f'I bought a {word}.'))
        self.assertEqual([['apple', 'I bought a apple.'], ['pear', 'I bought a pear.'],
                          ['apple', 'I bought a apple.']], [r['texts'] for r in self.requests()])
        self.assertIn('$voice.SpeakAsyncCancelAll()', self.speech.WORKER_SCRIPT)
        self.assertIn('$voice.SpeakAsync($prompt)', self.speech.WORKER_SCRIPT)
        self.assertNotIn('$voice.Speak(', self.speech.WORKER_SCRIPT)
        self.assertIn('$prompt.AppendText([string]$text)', self.speech.WORKER_SCRIPT)

    def test_manual_taps_are_suppressed_for_five_seconds(self):
        with patch.object(app.time, 'monotonic', return_value=100.0):
            self.assertTrue(self.speech.speak('apple'))
            self.assertFalse(self.speech.speak(' APPLE '))
        with patch.object(app.time, 'monotonic', return_value=104.999):
            self.assertFalse(self.speech.speak('apple'))
        with patch.object(app.time, 'monotonic', return_value=105.0):
            self.assertTrue(self.speech.speak('apple'))
        self.assertEqual(2, len(self.requests()))

    def test_automatic_play_also_suppresses_duplicate_manual_tap(self):
        self.assertTrue(self.speech.read_word('apple', 'She bought an apple.'))
        self.assertFalse(self.speech.speak('apple'))
        self.assertTrue(self.speech.read_word('apple', 'She bought an apple.'))

    def test_missing_example_and_stop_cancel_the_whole_sequence(self):
        self.assertTrue(self.speech.read_word('apple', ''))
        self.speech.stop()
        self.assertEqual([{'texts': ['apple']}, {'texts': []}], self.requests())
        self.assertFalse(self.speech.read_word(' ', 'A sentence.'))

    def test_idle_stop_does_not_launch_a_process(self):
        self.speech.process = None
        with patch.object(app.subprocess, 'Popen') as spawn:
            self.speech.stop()
            spawn.assert_not_called()

    def test_failed_request_does_not_use_up_the_cooldown(self):
        with patch.object(self.speech, '_send_locked', side_effect=[False, True]):
            self.assertFalse(self.speech.speak('apple'))
            self.assertTrue(self.speech.speak('apple'))

    def test_broken_worker_is_replaced_without_old_sentence(self):
        broken = Mock()
        broken.poll.return_value = None
        broken.stdin.write.side_effect = BrokenPipeError()
        self.speech.process = broken
        with patch.object(app.subprocess, 'Popen', return_value=self.process) as spawn:
            self.assertTrue(self.speech.read_word('pear', 'The pear is ripe.'))
            spawn.assert_called_once()
        broken.terminate.assert_called_once()
        self.assertEqual([{'texts': ['pear', 'The pear is ripe.']}], self.requests())

    def test_close_prevents_a_stale_callback_from_restarting_voice(self):
        self.speech.close()
        with patch.object(app.subprocess, 'Popen') as spawn:
            self.assertFalse(self.speech.read_word('apple', 'An apple is on the desk.'))
            spawn.assert_not_called()


class ExampleTests(unittest.TestCase):
    def test_startup_repairs_selected_store_not_a_different_cache_copy(self):
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / 'cache.json'
            real_path = Path(directory) / 'desktop.json'
            cache_path.write_text(json.dumps({'words': [{'id': 1, 'word': 'apple', 'meaning': '苹果',
                                    'example': 'A cached apple.'}], 'next_id': 2}), encoding='utf-8')
            original = {'words': [{'id': 8, 'word': 'delicacies', 'meaning': '美食', 'example': '',
                                  'total_reviews': 9, 'next_review': '2026-10-20'},
                                 {'id': 20, 'word': 'unlistedterm', 'meaning': '未列出词'}],
                        'next_id': 21, 'reviews': [{'word_id': 8, 'quality': 3}],
                        'active_session': {'words': [{'id': 8, 'word': 'delicacies', 'example': ''}]}}
            original_bytes = json.dumps(original).encode('utf-8')
            real_path.write_bytes(original_bytes)
            cache_bytes = cache_path.read_bytes()
            store = app.DataStore(real_path)
            self.assertEqual(cache_bytes, cache_path.read_bytes())
            self.assertEqual(2, len(store.words))
            self.assertEqual(9, store.words[0]['total_reviews'])
            self.assertEqual('2026-10-20', store.words[0]['next_review'])
            self.assertTrue(has_example(store.words[0]))
            self.assertEqual(original['words'][1], store.words[1])
            self.assertTrue(has_example(store.data['active_session']['words'][0]))
            backup = next(real_path.parent.glob('vocabulary-before-app-repair-*.json'))
            self.assertEqual(original_bytes, backup.read_bytes())
            self.assertEqual(store.words, app.DataStore(real_path).words)

    def test_lookup_repair_changes_examples_only_and_preserves_known_examples(self):
        data = {'words': [{'id': 1, 'word': 'actuator', 'meaning': '用户释义', 'total_reviews': 5},
                          {'id': 2, 'word': 'apple', 'example': 'My original example.', 'translation': '原译文'}]}
        repair_example_data(data, {'ACTUATOR': {'example': 'The machine has an actuator.', 'translation': '机器有一个执行器。',
                                               'meaning': '不应覆盖的释义'},
                                   'apple': {'example': 'Do not overwrite this.'}})
        self.assertEqual('用户释义', data['words'][0]['meaning'])
        self.assertEqual(5, data['words'][0]['total_reviews'])
        self.assertTrue(has_example(data['words'][0]))
        self.assertEqual('My original example.', data['words'][1]['example'])

    def test_local_examples_are_bilingual_and_existing_example_is_untouched(self):
        filled = complete_example({'word': 'crave', 'meaning': '渴望'}, required=True)
        self.assertIn('crave', filled['example'])
        self.assertTrue(filled['translation'])
        custom = {'word': 'crave', 'example': 'I crave a quiet afternoon.', 'translation': '我渴望安静的下午。'}
        self.assertEqual(custom, complete_example(custom))

    def test_lookup_of_missing_example_preserves_supplied_meaning(self):
        lookup = Mock(return_value={'meaning': '另一释义', 'example': 'The device uses a tiny actuator.',
                                    'translation': '该设备使用一个微型执行器。'})
        filled = enrich_entry({'word': 'actuator', 'meaning': '执行器'}, lookup)
        lookup.assert_called_once_with('actuator')
        self.assertEqual('执行器', filled['meaning'])
        self.assertTrue(has_example(filled))

    def test_missing_example_is_not_saved_individually_or_in_bulk(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / 'vocabulary.json')
            before = deepcopy(store.data)
            disk = store.path.read_bytes()
            with self.assertRaises(ValueError):
                store.add_word({'word': 'unknownentry', 'meaning': '未知词'})
            with self.assertRaises(ValueError):
                store.add_many([{'word': 'apple', 'meaning': '苹果'}, {'word': 'unknownentry', 'meaning': '未知词'}])
            self.assertEqual(before, store.data)
            self.assertEqual(disk, store.path.read_bytes())

    def test_known_entries_get_examples_offline(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / 'vocabulary.json')
            created = store.add_word({'word': ' CRAVE ', 'meaning': '渴望'})
            self.assertTrue(has_example(created))
            created, _ = store.add_many([{'word': 'apple', 'meaning': '苹果'}])
            self.assertTrue(has_example(created[0]))

    def test_lookup_without_an_example_is_rejected(self):
        with self.assertRaises(ValueError):
            enrich_entry({'word': 'unknownentry', 'meaning': '未知词'}, lambda _: {'meaning': '未知词'})

    def test_fill_preserves_progress_existing_examples_and_checkpoint_undo(self):
        word = {'id': 1, 'word': 'crave', 'meaning': '渴望', 'example': '', 'translation': '',
                'total_reviews': 7, 'next_review': '2026-10-10', 'level': 'learning'}
        custom = {'id': 2, 'word': 'apple', 'meaning': '苹果', 'example': 'An apple fell.', 'translation': '一个苹果落下。'}
        original = {'words': [word, custom], 'next_id': 3, 'reviews': [{'word_id': 1, 'quality': 2}],
                    'settings': {'theme': 'codex'}, 'essays': [{'original': 'My essay.'}],
                    'active_session': {'words': [deepcopy(word)], 'history': [{'words': [deepcopy(word)]}]}}
        snapshot = deepcopy(original)
        updated, changed = fill_module.fill_examples(original)
        self.assertEqual(['crave'], changed)
        self.assertEqual(snapshot, original)
        self.assertEqual(custom, updated['words'][1])
        for field in ('next_id', 'reviews', 'settings', 'essays'):
            self.assertEqual(original[field], updated[field])
        for field in word.keys() - {'example', 'translation'}:
            self.assertEqual(word[field], updated['words'][0][field])
        self.assertTrue(has_example(updated['active_session']['words'][0]))
        self.assertTrue(has_example(updated['active_session']['history'][0]['words'][0]))
        again, changed = fill_module.fill_examples(updated)
        self.assertEqual(updated, again)
        self.assertEqual([], changed)


if __name__ == '__main__':
    unittest.main()
