"""Fill missing examples only, with an atomic save and a recoverable data backup."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from example_bank import complete_example, has_example


def fill_examples(data):
    updated = deepcopy(data)
    changed = []
    for word in updated['words']:
        if not has_example(word):
            filled = complete_example(word, required=True)
            word['example'] = filled['example']
            word['translation'] = filled.get('translation', '')
            changed.append(word['word'])
    # A restored group contains its own copies, including undo history.
    def update_checkpoint(value):
        if isinstance(value, dict):
            if 'word' in value and 'id' in value and not has_example(value):
                filled = complete_example(value)
                if has_example(filled):
                    value['example'] = filled['example']
                    value['translation'] = filled.get('translation', '')
            for child in value.values():
                update_checkpoint(child)
        elif isinstance(value, list):
            for child in value:
                update_checkpoint(child)
    update_checkpoint(updated.get('active_session'))
    return updated, changed


if __name__ == '__main__':
    path = Path(os.environ['LOCALAPPDATA']) / 'EnglishVocabularyBook' / 'vocabulary.json'
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes)
    updated, changed = fill_examples(original)
    if changed or updated != original:
        # Refuse to overwrite a concurrent save from an open app.
        if path.read_bytes() != original_bytes:
            raise RuntimeError('词库刚刚被修改，请关闭软件后重新执行。')
        backup = path.with_name('vocabulary-before-examples-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
        shutil.copy2(path, backup)
        temporary = path.with_suffix('.examples.tmp')
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
        if path.read_bytes() != original_bytes:
            temporary.unlink()
            raise RuntimeError('检测到并发保存，原词库未覆盖。')
        temporary.replace(path)
        print('Backup:', backup)
    print(json.dumps({'added_examples': len(changed), 'total_entries': len(updated['words']),
                      'missing_examples': sum(not has_example(word) for word in updated['words']),
                      'learning_progress_preserved': True}, ensure_ascii=False))
