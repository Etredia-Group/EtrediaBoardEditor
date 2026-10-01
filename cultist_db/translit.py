# -*- coding: utf-8 -*-
"""Транслитерация кириллицы в безопасные имена каталогов."""
from __future__ import annotations

_VOWELS = set("еиоуяюaeiouy")


def deyo(text: str) -> str:
    """Убирает «йотацию»: 'ё'->'e', 'мя'->'ma', 'лья'->'lia' и т.п."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "й" and i + 1 < n and text[i + 1] in _VOWELS:
            i += 2                      # пропускаем йот
            continue
        if ch in ("ь", "ъ"):
            i += 1
            continue
        if ch == "ё":
            out.append("e")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
