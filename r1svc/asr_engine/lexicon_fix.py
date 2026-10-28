import os
import difflib
from pypinyin import lazy_pinyin, Style

_DEFAULT_LEXICON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "paraformer-small", "lexicon.txt",
)


class LexiconFix:
    """Pinyin-based proper-noun correction.

    lexicon.txt: one term per line, `name` or `name<TAB>wrong_spelling` (optional
    known ASR variants). Matching = exact pinyin sequence (with tone) of the term
    against any substring of the transcript; toneless as fallback; pinyin
    similarity (>=3 syllables) as last resort. Adding a new proper noun = adding
    a line to lexicon.txt, no code changes.
    """

    def __init__(self, path: str = None, fuzzy_toneless: bool = True):
        self.path = path or os.environ.get("LEXICON_FILE", _DEFAULT_LEXICON)
        self.entries = []  # (term, py_tone_str, py_toneless_str)
        self.wrong_spellings = {}  # wrong_spelling -> term
        self.fuzzy_toneless = fuzzy_toneless
        self.load()

    def load(self):
        self.entries.clear()
        self.wrong_spellings.clear()
        if not os.path.isfile(self.path):
            return
        with open(self.path, encoding="utf8") as f:
            for line in f:
                line = line.lstrip("﻿").strip()
                if not line or line.startswith("#"):
                    continue
                term, _, variant = line.partition("\t")
                term = term.strip()
                if not term:
                    continue
                if sum(1 for ch in term if "一" <= ch <= "龥") < 2:
                    continue  # non-CJK junk / separators
                py3 = lazy_pinyin(term, style=Style.TONE3)
                py0 = lazy_pinyin(term)
                if not py3 or not py0 or any(not p for p in py3 + py0):
                    continue  # no usable pinyin
                self.entries.append((term, " ".join(py3), " ".join(py0)))
                if variant:
                    self.wrong_spellings[variant.strip()] = term

    def fix(self, text: str) -> str:
        if not text or not self.entries:
            return text
        pys, pys0 = SpellCache.get(text)
        out = ""
        i = 0
        while i < len(text):
            matched = None
            # tier1: exact tone
            n = pys[i] and 0  # noqa - placeholder removed below
            for term, p3, p0 in self.entries:
                n = len(p3.split())
                if n == 0 or i + n > len(text):
                    continue
                if " ".join(pys[i:i + n]) == p3:
                    matched = (term, n)
                    break
            # tier2: toneless exact
            if not matched and self.fuzzy_toneless:
                for term, p3, p0 in self.entries:
                    n = len(p0.split())
                    if n == 0 or i + n > len(text):
                        continue
                    if " ".join(pys0[i:i + n]) == p0:
                        matched = (term, n)
                        break
            # tier3: pinyin fuzzy (initials like ji/qi confusion), >=3 syllables
            if not matched and self.fuzzy_toneless:
                best = None
                for term, p3, p0 in self.entries:
                    n = len(p0.split())
                    if n < 3 or i + n > len(text):
                        continue
                    w0 = " ".join(pys0[i:i + n])
                    ratio = difflib.SequenceMatcher(None, w0, p0).ratio()
                    if ratio >= 0.84 and (best is None or ratio > best[2]):
                        best = (term, n, ratio)
                if best:
                    matched = (best[0], best[1])
            if matched:
                term, n = matched
                out += term
                i += n
            else:
                out += text[i]
                i += 1
        for wrong, right in self.wrong_spellings.items():
            out = out.replace(wrong, right)
        return out


class SpellCache:
    """Per-char pinyin cache for transcripts. Non-CJK chars keep their
    lowercase form so windows stay aligned."""

    _cache = {}

    @classmethod
    def get(cls, text: str):
        v = cls._cache.get(text)
        if v is None:
            pys, pys0 = [], []
            for ch in text:
                if "一" <= ch <= "龥":
                    p = lazy_pinyin(ch, style=Style.TONE3)[0]
                    pys.append(p)
                    pys0.append(p.rstrip("012345"))
                else:
                    pys.append(ch.lower())
                    pys0.append(ch.lower())
            v = (pys, pys0)
            if len(cls._cache) > 4096:
                cls._cache.clear()
            cls._cache[text] = v
        return v
