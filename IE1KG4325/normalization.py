import re
import unicodedata
from enum import Enum

_LINEBREAKS_RE = re.compile(r"\r\n?|\u0085|\u2028|\u2029")

_ZERO_WIDTH_STRIP = dict.fromkeys(map(ord, [
    "\u200B", "\u2060", "\uFEFF", "\u180E", "\u034F",
]))

_UNICODE_SPACES = [
    "\u00A0", "\u1680", "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
    "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200A",
    "\u202F", "\u205F", "\u3000", "\t", "\x0b", "\x0c"
]
_SPACE_TO_ASCII = {ord(ch): " " for ch in _UNICODE_SPACES}


def normalize_spaces(text: str, collapse_internal_spaces: bool = True, tibetan_specific: bool = True) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r"\n{2,}", "\n", s)
    s = re.sub(r"[ ]+\n", "\n", s)
    s = re.sub(r"\n[ ]+", "\n", s)
    if collapse_internal_spaces:
        s = re.sub(r" {2,}", " ", s)
    if tibetan_specific:
        s = re.sub(r"([\u0f0b\u0f0c\u0fd2]) +([\u0f40-\u0f6c\u0f0d-\u0f11])", r"\1\2", s)
        s = re.sub(r"([\u0f40-\u0fbc]) +([\u0f0b\u0f0c\u0fd2])", r"\1\2", s)
    return s


def normalize_unicode(text: str, strip_control: bool = True, collapse_internal_spaces: bool = True) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text)
    s = _LINEBREAKS_RE.sub("\n", s)
    s = s.translate(_ZERO_WIDTH_STRIP)
    s = s.translate(_SPACE_TO_ASCII)
    if strip_control:
        s = "".join(ch for ch in s if ch == "\n" or (unicodedata.category(ch)[0] != "C"))
    s = normalize_spaces(s, collapse_internal_spaces=collapse_internal_spaces)
    s = normalize_unicode_tib(s)
    s = s.replace("\u0f0c", "\u0f0b")
    s = s.replace("\u0f0e", "\u0f0d\u0f0d")
    return s


class Cats(Enum):
    Other = 0
    Base = 1
    Subscript = 2
    BottomVowel = 3
    BottomMark = 4
    TopVowel = 5
    TopMark = 6
    RightMark = 7


CATEGORIES = (
    [Cats.Other] + [Cats.Base] + [Cats.Other] * 22 + [Cats.BottomVowel] * 2 +
    [Cats.Other] * 6 + [Cats.Base] * 20 + [Cats.Other] + [Cats.BottomMark] +
    [Cats.Other] + [Cats.BottomMark] + [Cats.Other] + [Cats.Subscript] +
    [Cats.Other] * 4 + [Cats.RightMark] + [Cats.Other] + [Cats.Base] * 45 +
    [Cats.Other] * 4 + [Cats.BottomVowel] + [Cats.TopVowel] + [Cats.TopVowel] +
    [Cats.BottomVowel] * 2 + [Cats.TopVowel] * 8 + [Cats.TopMark] +
    [Cats.RightMark] + [Cats.TopVowel] * 2 + [Cats.TopMark] * 2 +
    [Cats.BottomMark] + [Cats.Other] + [Cats.TopMark] * 2 + [Cats.Base] * 2 +
    [Cats.Base] + [Cats.Other] + [Cats.Base] + [Cats.Subscript] * 48
)


def charcat(c):
    o = ord(c)
    if 0x0F00 <= o <= 0x0FBC:
        return CATEGORIES[o - 0x0F00]
    return Cats.Other


def unicode_reorder(txt):
    charcats = [charcat(c) for c in txt]
    i = 0
    res = []
    valid = True
    while i < len(charcats):
        c = charcats[i]
        if c != Cats.Base:
            if c.value > Cats.Base.value:
                valid = False
            res.append(txt[i])
            i += 1
            continue
        j = i + 1
        while j < len(charcats) and charcats[j].value > Cats.Base.value:
            j += 1
        newindices = sorted(range(i, j), key=lambda e: (charcats[e].value, e))
        replaces = "".join(txt[n] for n in newindices)
        res.append(replaces)
        i = j
    return "".join(res), valid


def normalize_unicode_tib(s, form="nfd"):
    s = s.replace("\u0f73", "\u0f71\u0f72")
    s = s.replace("\u0f75", "\u0f71\u0f74")
    s = s.replace("\u0f77", "\u0fb2\u0f71\u0f80")
    s = s.replace("\u0f79", "\u0fb3\u0f71\u0f80")
    s = s.replace("\u0f81", "\u0f71\u0f80")
    if form == "nfd":
        s = s.replace("\u0f43", "\u0f42\u0fb7")
        s = s.replace("\u0f4d", "\u0f4c\u0fb7")
        s = s.replace("\u0f52", "\u0f51\u0fb7")
        s = s.replace("\u0f57", "\u0f56\u0fb7")
        s = s.replace("\u0f5c", "\u0f5b\u0fb7")
        s = s.replace("\u0f69", "\u0f40\u0fb5")
        s = s.replace("\u0f76", "\u0fb2\u0f80")
        s = s.replace("\u0f78", "\u0fb3\u0f80")
        s = s.replace("\u0f93", "\u0f92\u0fb7")
        s = s.replace("\u0f9d", "\u0f9c\u0fb7")
        s = s.replace("\u0fa2", "\u0fa1\u0fb7")
        s = s.replace("\u0fa7", "\u0fa6\u0fb7")
        s = s.replace("\u0fac", "\u0fab\u0fb7")
        s = s.replace("\u0fb9", "\u0f90\u0fb5")
    s = s.replace("\u0f00", "\u0f68\u0f7c\u0f7e")
    s, valid = unicode_reorder(s)
    s = re.sub("\u0f65(?![\u0f90-\u0f97\u0f9a-\u0fac\u0fae\u0faf\u0fb4-\u0fbc])", "ར", s)
    s = normalize_invalid_start_string(s)
    return s


def is_vowel(char):
    return bool(re.search(r"[\u0f71-\u0f84]", char))


def is_suffix(char):
    return bool(re.search(r"[\u0f90-\u0fbc]", char))


def normalize_invalid_start_string(s):
    if len(s) < 2:
        return s
    if is_vowel(s[0]) and not is_vowel(s[1]) and not is_suffix(s[1]):
        return s[1] + s[0] + (s[2:] if len(s) > 2 else "")
    if is_suffix(s[0]):
        return s[1:]
    return s






