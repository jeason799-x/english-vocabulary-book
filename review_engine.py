"""Local, transparent practice scheduling; no proprietary algorithm claims."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import random
import uuid


def plan_review(word: dict, quality: int, day: date | None = None) -> dict:
    day = day or date.today()
    quality = max(1, min(3, quality))
    previous = max(0, int(word.get("interval_days", 0)))
    if not previous and word.get("last_review") and word.get("next_review"):
        try:
            previous = max(0, (date.fromisoformat(word["next_review"]) - date.fromisoformat(word["last_review"])).days)
        except ValueError:
            pass
    ease = float(word.get("ease", 2.2))
    if quality == 1:
        interval, ease = 1, max(1.4, ease - .25)
    elif quality == 2:
        interval, ease = max(1, round(previous * .6)), max(1.4, ease - .12)
    else:
        interval = 1 if previous == 0 else min(120, max(previous + 1, round(previous * ease)))
        ease = min(2.8, ease + .05)
    return {
        "interval_days": interval, "ease": round(ease, 2),
        "correct_streak": int(word.get("correct_streak", 0)) + 1 if quality == 3 else 0,
        "total_reviews": int(word.get("total_reviews", 0)) + 1,
        "last_review": day.isoformat(), "next_review": (day + timedelta(days=interval)).isoformat(),
        "level": "mastered" if interval >= 15 and quality == 3 else "learning",
    }


class PracticeSession:
    """Shuffled queue, delayed retries, checkpoints and reversible answers."""
    def __init__(self, words: list[dict], mode: str, spelling: str, seed: int | None = None):
        self.rng = random.Random(seed)
        self.id = uuid.uuid4().hex
        self.mode, self.spelling = mode, spelling
        self.words = deepcopy(words)
        self.states = {str(w["id"]): {"solved": [], "required": ["recognize", "meaning", "recall"],
                                     "quality": 3, "errors": 0, "introduced": mode != "learn",
                                     "spelling_added": False} for w in words}
        self.queue = [{"word_id": w["id"], "kind": kind} for w in words
                      for kind in ("recognize", "meaning", "recall")]
        self.rng.shuffle(self.queue)
        self.current = None
        self.history = []
        self.answers = 0
        self.last_word = None
        self._next()

    def word(self) -> dict:
        return next(w for w in self.words if w["id"] == self.current["word_id"])

    def _next(self) -> None:
        if not self.queue:
            self.current = None
            return
        # Avoid consecutive appearances whenever another word is available.
        index = next((i for i, q in enumerate(self.queue) if q["word_id"] != self.last_word), 0)
        self.current = self.queue.pop(index)
        key = str(self.current["word_id"])
        if self.mode == "learn" and not self.states[key]["introduced"]:
            self.queue.insert(0, self.current)
            self.current = {"word_id": self.current["word_id"], "kind": "study"}
        if self.current["kind"] == "meaning":
            correct = self.word()["meaning"]
            distractors = list(dict.fromkeys(w["meaning"] for w in self.words if w["meaning"] != correct))
            self.rng.shuffle(distractors)
            choices = [correct] + distractors[:3]
            self.rng.shuffle(choices)
            self.current["choices"] = choices
        self.last_word = self.current["word_id"]

    def answer(self, correct: bool, quality: int = 3) -> None:
        if self.current is None:
            raise ValueError("本组已完成")
        self.history.append(self.snapshot(include_history=False))
        self.history = self.history[-100:]
        key, kind = str(self.current["word_id"]), self.current["kind"]
        state = self.states[key]
        if kind == "study":
            state["introduced"] = True
        else:
            self.answers += 1
            state["quality"] = min(state["quality"], quality if correct else 1)
            if correct:
                if kind not in state["solved"]:
                    state["solved"].append(kind)
            else:
                state["errors"] += 1
                self.queue.insert(min(len(self.queue), self.rng.randint(2, 4)),
                                  {"word_id": self.current["word_id"], "kind": kind})
            if not state["spelling_added"] and all(k in state["solved"] for k in ("recognize", "meaning", "recall")):
                state["spelling_added"] = True
                if self.spelling == "all" or (self.spelling == "errors" and state["quality"] < 3):
                    state["required"].append("spelling")
                    self.queue.insert(self.rng.randrange(len(self.queue) + 1),
                                      {"word_id": self.current["word_id"], "kind": "spelling"})
        self._next()

    @property
    def completed_count(self) -> int:
        return sum(all(k in s["solved"] for k in s["required"]) for s in self.states.values())

    @property
    def finished(self) -> bool:
        return self.current is None and self.completed_count == len(self.words)

    def undo(self) -> bool:
        if not self.history:
            return False
        previous = self.history.pop()
        history = self.history
        restored = self.restore(previous)
        self.__dict__.update(restored.__dict__)
        self.history = history
        return True

    def snapshot(self, include_history: bool = True) -> dict:
        return deepcopy({"id": self.id, "mode": self.mode, "spelling": self.spelling,
                         "words": self.words, "states": self.states, "queue": self.queue,
                         "current": self.current, "answers": self.answers, "last_word": self.last_word,
                         "random_state": self.rng.getstate(), "history": self.history if include_history else []})

    @classmethod
    def restore(cls, payload: dict) -> "PracticeSession":
        result = cls.__new__(cls)
        data = deepcopy(payload)
        random_state = data.pop("random_state")
        result.__dict__.update(data)
        result.rng = random.Random()
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, (list, tuple)) else value
        result.rng.setstate(tuples(random_state))
        return result
