import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_review_engine import app
from essay_library import SAMPLE_ESSAY, word_count, parse_expression_lines, format_expression_lines, vocabulary_payloads, parse_essay_text


def complete_sample_text(code='CET6_202512_W_02'):
    templates = '\n\n'.join(f"{i}. **{row['expression']}**\n   —— {row['note']}"
                              for i, row in enumerate(SAMPLE_ESSAY['templates'], 1))
    return f"**{code}**\n\n{SAMPLE_ESSAY['original']}\n\n**中文翻译：**\n\n{SAMPLE_ESSAY['translation']}\n\n**值得背诵的模板句子/短语及说明：**\n\n{templates}\n\n**写作思路：**\n\n{SAMPLE_ESSAY['thinking']}"


class EssayLibraryTests(unittest.TestCase):
    def test_complete_message_format_and_persisted_source(self):
        source = complete_sample_text()
        parsed = parse_essay_text(source)
        self.assertEqual('CET6_202512_W_02', parsed['code'])
        for field in ('original', 'translation', 'thinking'):
            self.assertEqual(SAMPLE_ESSAY[field], parsed[field])
        self.assertEqual(18, len(parsed['collocations']))
        self.assertEqual(6, len(parsed['templates']))
        for expected, actual in zip(SAMPLE_ESSAY['templates'], parsed['templates']):
            self.assertEqual(expected['expression'], actual['expression'])
            self.assertEqual(expected['note'], actual['meaning'])
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / 'vocabulary.json')
            before_words = json.dumps(store.words, sort_keys=True)
            store.save_essay(parsed)
            self.assertEqual(source, app.DataStore(store.path).essays[0]['source_text'])
            self.assertEqual(before_words, json.dumps(store.words, sort_keys=True))

    def test_explicit_collocations_and_local_known_expressions(self):
        source = '# Essay_02\n标题：练习\n主题：学习\n\n## 英文原文\nWe pay attention to learning.\n## 中文翻译\n我们关注学习。\n## 固定搭配\n1. **pay attention to**\n—— 注意；关注\n2. take notes | 记笔记 | 学习话题\n## 写作思路\n先引出学习。'
        parsed = parse_essay_text(source, [{'word': 'pay attention to', 'meaning': '旧释义', 'usage': '旧说明'},
                                         {'word': 'focus on', 'meaning': '集中注意力于'}])
        self.assertEqual('练习', parsed['title'])
        self.assertEqual('学习', parsed['topic'])
        self.assertEqual(['pay attention to', 'take notes'], [r['expression'] for r in parsed['collocations']])
        self.assertEqual('注意；关注', parsed['collocations'][0]['meaning'])
        parsed = parse_essay_text('Essay_03\nWe pay attention to learning.', [{'word': 'pay attention to', 'meaning': '注意'}])
        self.assertEqual('pay attention to', parsed['collocations'][0]['expression'])

    def test_incomplete_pasted_material_does_not_create_a_record(self):
        for source in ('', '这是一篇文章\nEnglish essay', 'Essay_04\n**中文翻译：**\n中文',
                       'Essay_04\nEnglish essay.\n**固定搭配：**\npay attention to'):
            with self.assertRaises(ValueError):
                parse_essay_text(source)

    def test_old_store_migration_preserves_vocabulary_and_progress(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'vocabulary.json'
            original = {'schema_version': 3, 'next_id': 2, 'words': [{'id': 1, 'word': 'apple', 'meaning': '苹果',
                         'total_reviews': 5, 'last_review': '2026-09-30'}], 'reviews': [{'word_id': 1, 'quality': 2}],
                        'active_session': {'unfinished': True}, 'settings': {'theme': 'rose'}}
            path.write_text(json.dumps(original), encoding='utf-8')
            store = app.DataStore(path)
            essay = store.save_essay(SAMPLE_ESSAY)
            loaded = app.DataStore(path)
            self.assertEqual(essay, loaded.essays[0])
            for field in ('reviews', 'active_session', 'next_id'):
                self.assertEqual(original[field], loaded.data[field])
            self.assertEqual(original['words'], [{key: value for key, value in word.items() if key not in ('example', 'translation')}
                                                for word in loaded.words])
            self.assertTrue(loaded.words[0]['example'])
            self.assertEqual('rose', loaded.settings['theme'])
            self.assertEqual(SAMPLE_ESSAY['original'], loaded.essays[0]['original'])
            self.assertEqual(18, len(loaded.essays[0]['collocations']))
            self.assertEqual(6, len(loaded.essays[0]['templates']))

    def test_update_duplicate_validation_and_save_failure(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / 'vocabulary.json')
            essay = store.save_essay(SAMPLE_ESSAY)
            before = json.dumps(store.data, sort_keys=True)
            disk = store.path.read_bytes()
            with self.assertRaises(ValueError):
                store.save_essay({**SAMPLE_ESSAY, 'code': SAMPLE_ESSAY['code'].lower()})
            with self.assertRaises(ValueError):
                store.save_essay({**SAMPLE_ESSAY, 'original': ' '})
            with patch.object(store, 'save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    store.save_essay({**SAMPLE_ESSAY, 'title': '未保存'}, essay['id'])
                with self.assertRaises(OSError):
                    store.delete_essay(essay['id'])
            self.assertEqual(before, json.dumps(store.data, sort_keys=True))
            self.assertEqual(disk, store.path.read_bytes())
            updated = store.save_essay({**SAMPLE_ESSAY, 'title': '已编辑'}, essay['id'])
            self.assertEqual(essay['id'], updated['id'])
            self.assertEqual(essay['created_at'], updated['created_at'])
            self.assertEqual(1, len(store.essays))
            self.assertEqual('已编辑', app.DataStore(store.path).essays[0]['title'])

    def test_collocations_enter_existing_review_flow_and_survive_essay_deletion(self):
        with TemporaryDirectory() as directory:
            store = app.DataStore(Path(directory) / 'vocabulary.json')
            store.add_word({'word': 'first and foremost', 'meaning': '原有释义', 'entry_type': 'phrase'})
            original_words = json.loads(json.dumps(store.words))
            essay = store.save_essay(SAMPLE_ESSAY)
            created, skipped = store.add_many(vocabulary_payloads(essay))
            self.assertEqual(17, len(created))
            self.assertEqual(1, skipped)
            self.assertEqual(original_words, store.words[:len(original_words)])
            self.assertTrue(all(word['entry_type'] == 'phrase' and word['total_reviews'] == 0 for word in created))
            again, skipped = store.add_many(vocabulary_payloads(essay))
            self.assertEqual([], again)
            self.assertEqual(18, skipped)
            words = json.loads(json.dumps(store.words))
            store.delete_essay(essay['id'])
            loaded = app.DataStore(store.path)
            self.assertEqual([], loaded.essays)
            self.assertEqual(words, loaded.words)

    def test_expression_editor_roundtrip_and_incomplete_rows(self):
        for field in ('collocations', 'templates'):
            self.assertEqual(SAMPLE_ESSAY[field], parse_expression_lines(format_expression_lines(SAMPLE_ESSAY[field])))
        self.assertEqual('中文', parse_expression_lines('english\t中文\t说明')[0]['meaning'])
        self.assertEqual('', parse_expression_lines('pay attention to | 注意')[0]['note'])
        with self.assertRaises(ValueError):
            parse_expression_lines('pay attention to | ')

    def test_word_count_ignores_markdown_and_handles_apostrophes(self):
        self.assertEqual(5, word_count("**It's** a well-known writing technique."))
        self.assertTrue(150 <= word_count(SAMPLE_ESSAY['original']) <= 200)


if __name__ == '__main__':
    unittest.main()
