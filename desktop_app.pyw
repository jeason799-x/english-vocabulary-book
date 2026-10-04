from __future__ import annotations
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from desktop_interface import VocabularyWindow
from review_engine import plan_review
from vocabulary_items import normalize_expression, item_type
from bulk_import import split_duplicates
from essay_library import normalize_essay
from example_bank import complete_example, repair_example_data

APP_NAME = "英语生词本"
APP_VERSION = "2.4.0"
SPEECH_COOLDOWN_SECONDS = 5.0

POS_ZH = {
    "noun": "名词",
    "verb": "动词",
    "adjective": "形容词",
    "adverb": "副词",
    "pronoun": "代词",
    "preposition": "介词",
    "conjunction": "连词",
    "interjection": "感叹词",
    "exclamation": "感叹词",
    "determiner": "限定词",
    "article": "冠词",
    "numeral": "数词",
    "n": "名词",
    "v": "动词",
    "vt": "及物动词",
    "vi": "不及物动词",
    "adj": "形容词",
    "adv": "副词",
    "prep": "介词",
    "pron": "代词",
    "conj": "连词",
    "art": "冠词",
    "num": "数词",
    "interj": "感叹词",
}

STARTER_WORDS = [
    {
        "word": "nonetheless",
        "phonetic": "/ˌnʌnðəˈles/",
        "part_of_speech": "副词",
        "meaning": "尽管如此；不过；然而",
        "usage": "用于承认前面所说的事实，同时引出转折。语气比 but 更正式。",
        "example": "The task was difficult. Nonetheless, she completed it on time.",
        "translation": "这项任务很困难。尽管如此，她还是按时完成了。",
    },
    {
        "word": "generalize",
        "phonetic": "/ˈdʒenrəlaɪz/",
        "part_of_speech": "动词",
        "meaning": "概括；归纳；推广；使适用于更广泛的情况",
        "usage": "常见搭配：generalize from、generalize about、generalize to。",
        "example": "It is dangerous to generalize from a single example.",
        "translation": "仅凭一个例子就得出普遍结论是很危险的。",
    },
    {
        "word": "suppression",
        "phonetic": "/səˈpreʃən/",
        "part_of_speech": "名词",
        "meaning": "压制；抑制；压抑；隐瞒",
        "usage": "suppression 常指有意识地压下；repression 常指无意识的压抑。",
        "example": "Long-term suppression of emotions can increase stress.",
        "translation": "长期压抑情绪可能会增加压力。",
    },
]

def today_text():
    return date.today().isoformat()


def clean_html(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_phonetic(value: str) -> str:
    value = value.strip().strip("/")
    return f"/{value}/" if value else ""


class DataStore:
    def __init__(self, path: Path | None = None) -> None:
        local_root = os.environ.get("LOCALAPPDATA")
        if local_root:
            self.directory = Path(local_root) / "EnglishVocabularyBook"
        else:
            self.directory = Path(sys.executable).resolve().parent / "data"
        if path is not None:
            self.directory = path.parent
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = path or self.directory / "vocabulary.json"
        self.data = self._load()
        self.data.setdefault("reviews", [])
        self.data.setdefault("active_session", None)
        self.data.setdefault("settings", {})
        defaults = {"theme": "codex", "glass_enabled": True, "group_size": 10, "learn_spelling": "all", "review_spelling": "errors"}
        for key, value in defaults.items():
            self.data["settings"].setdefault(key, value)
        self.data.setdefault("essays", [])
        self.data["schema_version"] = 5
        # Repair from inside the running app, where Windows resolves its actual
        # data file. An external packaged tool may see a different AppData copy.
        self.repair_examples()

    def repair_examples(self, updates=None) -> int:
        before = deepcopy(self.data)
        changed = repair_example_data(self.data, updates)
        if not changed:
            return 0
        try:
            if self.path.exists():
                stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                shutil.copy2(self.path, self.path.with_name(f'vocabulary-before-app-repair-{stamp}.json'))
            self.save()
        except OSError as error:
            self.data = before
            raise RuntimeError('例句未能写入，原词库和学习进度已保留：' + str(self.path)) from error
        return changed

    def _load(self) -> dict:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded.get("words"), list):
                    return loaded
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("生词本读取失败，原文件已保留：" + str(self.path)) from error
            raise RuntimeError("生词本格式异常，原文件已保留：" + str(self.path))
        data = {"schema_version": 1, "next_id": 1, "words": [], "reviews": []}
        self._seed(data)
        self._save_data(data)
        return data

    def _seed(self, data: dict) -> None:
        progress_by_word: dict[str, dict] = {}
        candidates = [
            Path.cwd().parent / "复习进度.json",
            Path(sys.executable).resolve().parent.parent / "复习进度.json",
            Path(sys.executable).resolve().parent.parent.parent / "复习进度.json",
            Path(__file__).resolve().parent.parent / "复习进度.json",
        ]
        for candidate in candidates:
            try:
                progress = json.loads(candidate.read_text(encoding="utf-8"))
                progress_by_word = {
                    str(item.get("word", "")).lower(): item
                    for item in progress.get("words", [])
                }
                break
            except (OSError, json.JSONDecodeError):
                continue

        for starter in STARTER_WORDS:
            progress = progress_by_word.get(starter["word"], {})
            word = {
                "id": data["next_id"],
                **starter,
                "level": progress.get("level", "new"),
                "correct_streak": int(progress.get("correct_streak", 0)),
                "total_reviews": int(progress.get("total_reviews", 0)),
                "last_review": progress.get("last_review"),
                "next_review": progress.get("next_review", today_text()),
                "created_at": today_text(),
            }
            data["words"].append(word)
            data["next_id"] += 1

    def _save_data(self, data: dict) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    def save(self) -> None:
        self._save_data(self.data)

    @property
    def words(self) -> list[dict]:
        return self.data["words"]

    def add_word(self, payload: dict) -> dict:
        normalized = normalize_expression(payload["word"])
        if not normalized or not payload.get("meaning", "").strip():
            raise ValueError("英文内容和中文释义不能为空。")
        if any(normalize_expression(item["word"]) == normalized for item in self.words):
            raise ValueError("这条内容已经在生词本里了。")
        payload = complete_example(payload, required=True)
        word = {
            "id": self.data["next_id"],
            "word": normalized,
            "entry_type": item_type({**payload, "word": normalized}),
            "phonetic": payload.get("phonetic", "").strip(),
            "part_of_speech": payload.get("part_of_speech", "").strip(),
            "meaning": payload.get("meaning", "").strip(),
            "usage": payload.get("usage", "").strip(),
            "example": payload.get("example", "").strip(),
            "translation": payload.get("translation", "").strip(),
            "level": "new",
            "correct_streak": 0,
            "total_reviews": 0,
            "last_review": None,
            "next_review": today_text(),
            "created_at": today_text(),
        }
        self.data["next_id"] += 1
        self.words.append(word)
        try:
            self.save()
        except OSError:
            self.words.pop()
            self.data["next_id"] -= 1
            raise
        return word

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def add_many(self, payloads: list[dict]) -> tuple[list[dict], int]:
        unique, duplicates = split_duplicates(payloads, self.words)
        if any(not p.get("word", "").strip() or not p.get("meaning", "").strip() for p in unique):
            raise ValueError("要导入的每条内容都需要英文和中文释义。")
        unique = [complete_example(payload, required=True) for payload in unique]
        before = deepcopy(self.data)
        created = []
        try:
            for payload in unique:
                word = {key: str(payload.get(key, "")).strip() for key in
                        ("phonetic", "part_of_speech", "meaning", "usage", "example", "translation")}
                word.update(id=self.data["next_id"], word=normalize_expression(payload["word"]), entry_type=item_type(payload),
                            level="new", correct_streak=0, total_reviews=0, last_review=None,
                            next_review=today_text(), created_at=today_text())
                self.data["next_id"] += 1
                self.words.append(word)
                created.append(word)
            if created:
                self.save()
        except OSError:
            self.data = before
            raise
        return created, duplicates

    @property
    def essays(self) -> list[dict]:
        return self.data["essays"]

    def save_essay(self, payload: dict, essay_id: str | None = None) -> dict:
        previous = next((item for item in self.essays if item["id"] == essay_id), None)
        if essay_id is not None and previous is None:
            raise ValueError("这篇作文已经不存在，请重新打开作文目录。")
        record = normalize_essay(payload, previous)
        if any(item["code"].casefold() == record["code"].casefold() and item["id"] != essay_id for item in self.essays):
            raise ValueError("这个作文编号已存在，请换一个编号，或编辑原作文。")
        before = deepcopy(self.data)
        if previous:
            self.essays[self.essays.index(previous)] = record
        else:
            self.essays.append(record)
        try:
            self.save()
        except OSError:
            self.data = before
            raise
        return record

    def delete_essay(self, essay_id: str) -> None:
        before = deepcopy(self.data)
        self.data["essays"] = [item for item in self.essays if item["id"] != essay_id]
        try:
            self.save()
        except OSError:
            self.data = before
            raise

    def commit_session(self, session) -> list[dict]:
        if not session.finished:
            raise ValueError("本组练习尚未完成")
        ids = {w["id"] for w in session.words}
        if any(e.get("session_id") == session.id for e in self.data["reviews"]):
            return [w for w in self.words if w["id"] in ids]
        before = deepcopy(self.data)
        result = []
        try:
            for word in self.words:
                if word["id"] not in ids:
                    continue
                state = session.states[str(word["id"])]
                quality = state["quality"]
                word.update(plan_review(word, quality))
                self.data["reviews"].append({"word_id": word["id"], "word": word["word"],
                    "known": quality == 3, "quality": quality, "errors": state["errors"],
                    "date": today_text(), "session_id": session.id, "mode": session.mode})
                result.append(word)
            self.data["active_session"] = None
            self.save()
        except OSError:
            self.data = before
            raise
        return result


def fetch_json(url: str, timeout: int = 9) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"EnglishVocabularyBook/{APP_VERSION}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def translate_text(text: str) -> str:
    if not text:
        return ""
    query = urllib.parse.urlencode({"q": text[:450], "langpair": "en|zh-CN"})
    try:
        data = fetch_json(f"https://api.mymemory.translated.net/get?{query}")
        if isinstance(data, dict):
            translated = clean_html(data.get("responseData", {}).get("translatedText", ""))
            if translated and translated.lower() != text.lower():
                return translated
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return ""


def lookup_youdao(word: str) -> dict:
    result = {"word": word}
    url = "https://dict.youdao.com/jsonapi?" + urllib.parse.urlencode({"q": word})
    data = fetch_json(url)
    if not isinstance(data, dict):
        return result

    ec_words = data.get("ec", {}).get("word", [])
    if ec_words:
        entry = ec_words[0]
        phone = entry.get("usphone") or entry.get("ukphone") or entry.get("phone") or ""
        result["phonetic"] = normalize_phonetic(clean_html(phone))
        translations: list[str] = []
        pos_values: list[str] = []
        for group in entry.get("trs", []):
            items = group.get("tr", []) if isinstance(group, dict) else []
            for item in items:
                values = item.get("l", {}).get("i", []) if isinstance(item, dict) else []
                if isinstance(values, str):
                    values = [values]
                for value in values:
                    cleaned = clean_html(value)
                    if cleaned and cleaned not in translations:
                        translations.append(cleaned)
                        match = re.match(r"^([a-z]+)\.", cleaned, re.I)
                        if match:
                            pos = POS_ZH.get(match.group(1).lower(), match.group(1))
                            if pos not in pos_values:
                                pos_values.append(pos)
        result["meaning"] = "；".join(translations[:4])
        result["part_of_speech"] = "、".join(pos_values[:3])

    sentence_pairs = data.get("blng_sents_part", {}).get("sentence-pair", [])
    if not sentence_pairs:
        sentence_pairs = data.get("blng_sents_sentence_pair", [])
    if sentence_pairs:
        pair = sentence_pairs[0]
        if isinstance(pair, dict):
            result["example"] = clean_html(
                pair.get("sentence") or pair.get("sentence-eng") or pair.get("sentence_eng")
            )
            result["translation"] = clean_html(
                pair.get("sentence-translation")
                or pair.get("sentence-translation-speech")
                or pair.get("sentence_translation")
            )
    return result


def lookup_dictionary(word: str) -> dict:
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    data = fetch_json(url)
    if not isinstance(data, list) or not data:
        return {"word": word}

    entry = data[0]
    phonetic = clean_html(entry.get("phonetic", ""))
    if not phonetic:
        for item in entry.get("phonetics", []):
            phonetic = clean_html(item.get("text", ""))
            if phonetic:
                break

    definitions: list[str] = []
    examples: list[str] = []
    parts: list[str] = []
    for meaning in entry.get("meanings", []):
        part = clean_html(meaning.get("partOfSpeech", ""))
        if part and part not in parts:
            parts.append(part)
        for definition in meaning.get("definitions", []):
            text = clean_html(definition.get("definition", ""))
            if text and text not in definitions:
                definitions.append(text)
            example = clean_html(definition.get("example", ""))
            if example and example not in examples:
                examples.append(example)

    translated_definitions = [translate_text(item) for item in definitions[:2]]
    translated_definitions = [item for item in translated_definitions if item]
    example = examples[0] if examples else ""
    return {
        "word": clean_html(entry.get("word", word)) or word,
        "phonetic": normalize_phonetic(phonetic),
        "part_of_speech": "、".join(POS_ZH.get(item, item) for item in parts[:3]),
        "meaning": "；".join(translated_definitions),
        "usage": "英文释义：" + "；".join(definitions[:2]) if definitions else "",
        "example": example,
        "translation": translate_text(example),
    }


def lookup_word(word: str) -> dict:
    normalized = normalize_expression(word)
    if not re.fullmatch(r"[a-z][a-z\-' .()/]*", normalized, re.I):
        raise ValueError("请输入英文单词或完整搭配，例如 pay attention to。")

    combined = {
        "word": normalized,
        "phonetic": "",
        "part_of_speech": "",
        "meaning": "",
        "usage": "",
        "example": "",
        "translation": "",
    }
    errors: list[Exception] = []
    providers = (lookup_youdao,) if item_type({"word": normalized}) == "phrase" else (lookup_youdao, lookup_dictionary)
    for provider in providers:
        try:
            found = provider(normalized)
            for key in combined:
                if not combined[key] and found.get(key):
                    combined[key] = str(found[key])
            if combined["meaning"] and combined["example"] and (len(providers) == 1 or combined["phonetic"]):
                break
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
            errors.append(error)

    if not combined["meaning"]:
        if errors:
            raise ConnectionError("没有查到这条内容，请检查拼写或网络。固定搭配也可以手动填写后保存。") from errors[-1]
        raise LookupError("没有查到这条内容，可以手动填写释义和例句后保存。")
    combined["entry_type"] = item_type({"word": normalized})
    return complete_example(combined)


class SpeechService:
    """Warm, interruptible speech; automatic cards bypass the manual tap limit."""

    WORKER_SCRIPT = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.Rate = -1
$voice.Volume = 100
$english = $voice.GetInstalledVoices() | Where-Object {
    $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en-*'
} | Select-Object -First 1
if ($english) { $voice.SelectVoice($english.VoiceInfo.Name) }
try {
    while ($null -ne ($line = [Console]::In.ReadLine())) {
        if ($line -eq '__QUIT__') { break }
        try {
            $bytes = [Convert]::FromBase64String($line)
            $request = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
            # Asynchronous synthesis leaves stdin free to receive the next card.
            # Purge both the current word and its pending example before replacing.
            $voice.SpeakAsyncCancelAll()
            $prompt = [System.Speech.Synthesis.PromptBuilder]::new($voice.Voice.Culture)
            $hasText = $false
            foreach ($text in $request.texts) {
                if (-not [String]::IsNullOrWhiteSpace($text)) {
                    if ($hasText) { $prompt.AppendBreak([TimeSpan]::FromMilliseconds(220)) }
                    $prompt.AppendText([string]$text)
                    $hasText = $true
                }
            }
            # One prompt prevents a cancelled word from starting a queued example.
            if ($hasText) { [void]$voice.SpeakAsync($prompt) }
        } catch {}
    }
} finally {
    $voice.SpeakAsyncCancelAll()
    $voice.Dispose()
}
""".strip()

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.last_spoken: dict[str, float] = {}
        self._closed = False

    def start(self) -> None:
        with self.lock:
            self._start_locked()

    def _start_locked(self) -> bool:
        if self._closed or os.name != "nt":
            return False
        if self.process and self.process.poll() is None:
            return True
        encoded = base64.b64encode(self.WORKER_SCRIPT.encode("utf-16le")).decode("ascii")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-EncodedCommand", encoded],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                text=True, encoding="ascii", bufsize=1, creationflags=creation_flags,
            )
        except OSError:
            self.process = None
            return False
        return True

    def _send_locked(self, texts: list[str]) -> bool:
        payload = base64.b64encode(json.dumps({"texts": texts}, ensure_ascii=False).encode("utf-8")).decode("ascii")
        for _ in range(2):
            if not self._start_locked() or not self.process or not self.process.stdin:
                return False
            try:
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
                return True
            except (BrokenPipeError, OSError):
                self._retire_locked()
        return False

    def _mark_spoken_locked(self, texts: list[str], now: float) -> None:
        self.last_spoken = {key: timestamp for key, timestamp in self.last_spoken.items()
                            if now - timestamp < SPEECH_COOLDOWN_SECONDS}
        for text in texts:
            self.last_spoken[text.casefold()] = now

    def read_word(self, word: str, example: str = "") -> bool:
        """Replace the entire previous card with word → example, even on revisits."""
        texts = [text.strip() for text in (word, example) if text and text.strip()]
        if not word or not word.strip():
            return False
        with self.lock:
            if not self._send_locked(texts):
                return False
            self._mark_spoken_locked(texts, time.monotonic())
            return True

    def speak(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        key = normalized.casefold()
        now = time.monotonic()
        with self.lock:
            if now - self.last_spoken.get(key, -SPEECH_COOLDOWN_SECONDS) < SPEECH_COOLDOWN_SECONDS:
                return False
            if not self._send_locked([normalized]):
                return False
            self._mark_spoken_locked([normalized], now)
            return True

    def stop(self) -> None:
        with self.lock:
            # Navigating away should not start a speech process just to stop it.
            if self.process and self.process.poll() is None:
                self._send_locked([])

    def _retire_locked(self) -> None:
        process, self.process = self.process, None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        if process.poll() is None:
            process.terminate()

    def close(self) -> None:
        with self.lock:
            self._closed = True
            process = self.process
            if not process:
                return
            try:
                if process.stdin:
                    process.stdin.write("__QUIT__\n")
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            self._retire_locked()


SPEECH = SpeechService()


def speak(text: str) -> bool:
    return SPEECH.speak(text)


class VocabularyApp(VocabularyWindow):
    def __init__(self, store=None, speech=None):
        super().__init__(store or DataStore(), lookup_word, speech or SPEECH, APP_VERSION)


def main():
    if "--smoke-test" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}: imports OK")
        return
    try:
        app = VocabularyApp()
    except RuntimeError as error:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("无法读取生词本", str(error), parent=window)
        window.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
