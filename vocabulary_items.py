"""Shared handling for single words and complete collocations."""
import re
import unicodedata


def normalize_expression(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(str.maketrans({
        "’": "'", "‘": "'", "‐": "-", "‑": "-", "–": "-", "…": "...",
    }))
    return re.sub(r"\s+", " ", value.strip()).casefold()


def item_type(item: dict) -> str:
    explicit = item.get("entry_type")
    return explicit if explicit in ("word", "phrase") else ("phrase" if " " in normalize_expression(item.get("word", "")) else "word")


def answer_matches(answer: str, target: str) -> bool:
    def key(value):
        value = normalize_expression(value)
        # Placeholder punctuation is optional; the prepositions and word order aren't.
        return re.sub(r"\b(sb|sth)\.(?=\s|$)", r"\1", value)
    return key(answer) == key(target)


_VERBS = {
    "be": "be|am|is|are|was|were|been|being", "have": "have|has|had|having",
    "take": "take|takes|took|taken|taking", "make": "make|makes|made|making",
    "pay": "pay|pays|paid|paying", "get": "get|gets|got|gotten|getting",
    "give": "give|gives|gave|given|giving", "keep": "keep|keeps|kept|keeping",
    "do": "do|does|did|done|doing", "go": "go|goes|went|gone|going",
    "look": "look|looks|looked|looking", "depend": "depend|depends|depended|depending",
    "prevent": "prevent|prevents|prevented|preventing",
}


def expression_pattern(expression: str) -> re.Pattern:
    tokens = normalize_expression(expression).split()
    pieces = []
    for i, token in enumerate(tokens):
        if token in ("sb", "sb.", "sth", "sth.", "someone", "somebody", "something"):
            pieces.append(r"[^.!?;\n]+?")
        elif token == "one's":
            pieces.append(r"(?:my|your|his|her|its|our|their|one['’]s|[A-Za-z]+['’]s)")
        elif i == 0 and len(tokens) > 1 and token in _VERBS:
            pieces.append("(?:" + _VERBS[token] + ")")
        else:
            pieces.append(re.escape(token).replace("'", "['’]").replace(r"\-", "[-‐‑–]"))
    return re.compile(r"(?<!\w)" + r"\s+".join(pieces) + r"(?!\w)", re.I)


def mask_example(example: str, expression: str) -> str:
    return expression_pattern(expression).sub("______", example)
