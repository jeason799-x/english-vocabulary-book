"""Parse pasted lists, Excel rows and CSV files without changing saved data."""
import csv
import io
import re
from vocabulary_items import normalize_expression, item_type

_HEADERS = {
    "word": "word", "expression": "word", "term": "word", "英文": "word", "英文单词": "word",
    "单词": "word", "词条": "word", "搭配": "word", "固定搭配": "word", "单词/搭配": "word",
    "meaning": "meaning", "释义": "meaning", "中文": "meaning", "中文释义": "meaning",
    "phonetic": "phonetic", "音标": "phonetic", "part_of_speech": "part_of_speech", "词性": "part_of_speech",
    "usage": "usage", "用法": "usage", "用法与搭配": "usage", "example": "example", "英文例句": "example", "例句": "example",
    "translation": "translation", "例句翻译": "translation", "type": "entry_type", "类型": "entry_type", "entry_type": "entry_type",
}
_TYPES = {"单词": "word", "word": "word", "固定搭配": "phrase", "搭配": "phrase", "phrase": "phrase", "collocation": "phrase"}


def parse_import(text: str) -> tuple[list[dict], list[str]]:
    text = text.lstrip("\ufeff")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = "\t" if "\t" in first else "," if "," in first else None
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter)) if delimiter else [[line] for line in text.splitlines()]
    records, errors = [], []
    header = None
    first_data = True
    for number, cells in enumerate(rows, 1):
        if not cells or not any(c.strip() for c in cells):
            continue
        if first_data and delimiter:
            mapped = [_HEADERS.get(c.strip().casefold()) for c in cells]
            if "word" in mapped and ("meaning" in mapped or len(cells) > 1):
                header = mapped
                first_data = False
                continue
        first_data = False
        payload = {}
        if delimiter:
            keys = header or ["word", "meaning", "example", "translation", "usage", "phonetic", "part_of_speech"]
            payload = {key: cells[i].strip() for i, key in enumerate(keys) if key and i < len(cells)}
        else:
            line = re.sub(r"^(?:[-*•]\s+|\d+[.)、]\s*)", "", cells[0].strip())
            chinese = re.search(r"[\u3400-\u9fff]", line)
            if chinese:
                payload = {"word": line[:chinese.start()].rstrip(" \t:：=|"), "meaning": line[chinese.start():].strip()}
                pos = re.search(r"\s+(n|v|adj|adv|prep|pron|conj|vt|vi)\.$", payload["word"])
                if pos:
                    payload["part_of_speech"] = pos.group(1) + "."
                    payload["word"] = payload["word"][:pos.start()]
            else:
                payload = {"word": line, "meaning": ""}
        payload["word"] = normalize_expression(payload.get("word", ""))
        if not re.fullmatch(r"[a-z][a-z\-' .()/]*", payload["word"]):
            errors.append(f"第 {number} 行：未识别英文内容")
            continue
        payload["entry_type"] = _TYPES.get(payload.get("entry_type", "").casefold(), "auto")
        payload["entry_type"] = item_type(payload)
        payload.setdefault("meaning", "")
        payload["source_row"] = number
        records.append(payload)
    return records, errors


def decode_import(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("gb18030")


def split_duplicates(records: list[dict], existing: list[dict]) -> tuple[list[dict], int]:
    seen = {normalize_expression(w["word"]) for w in existing}
    unique, duplicates = [], 0
    for record in records:
        key = normalize_expression(record["word"])
        if key in seen:
            duplicates += 1
        else:
            unique.append(record)
            seen.add(key)
    return unique, duplicates
