# -*- coding: utf-8 -*-
"""Схема данных менеджера игровых карт, приближённая к Cultist Simulator.

Каждая карта описывается набором атрибутов.  Атрибуты делятся на:

* скалярные (название, описание, flavor, уровень/веса, цвет, иконка);
* списочные уникальные (аспекты, теги, элементы, влияния);
* списочные НЕуникальные (ресурсы, склонности, часы, свойства, эмоции) —
  здесь один и тот же объект может встречаться несколько раз (count / stacks);
* связи (используется в, порождает, требует, отражает, альтер эго);
* правила трансмутации (transmutations) — подсловари карты.

Переиспользуемые объекты (ресурсы, аспекты, влияния, элементы, склонности,
часы, свойства, эмоции, теги, цвета, иконки, правила) хранятся в базе
отдельно в наборах (sets) и применяются к карте по slug'у через ссылки вида
``{"ref": "slug", "count": N}``.  Карта также может определять новый локальный
объект прямо в списке (``{"new": {...}}``) — при сохранении он «поднимается»
(promote) в переиспользуемый набор.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .translit import deyo

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Типы элементов базы (один тип == один набор == один JSON файл)
# ---------------------------------------------------------------------------
T_CARD = "card"
T_RESOURCE = "resource"
T_ASPECT = "aspect"
T_INFLUENCE = "influence"
T_ELEMENT = "element"
T_SUPPRESSION = "suppression"      # склонность (что ослабляет что)
T_HOURS = "hours"                  # часы / деления
T_PROPERTY = "property"            # свойства (неделимость, тайна...)
T_EMOTION = "emotion"              # эмоции / состояния
T_RULE = "rule"                    # правила трансмутации
T_TAG = "tag"
T_COLOR = "color"
T_ICON = "icon"

ELEMENT_TYPES = (
    T_CARD, T_RESOURCE, T_ASPECT, T_INFLUENCE, T_ELEMENT, T_SUPPRESSION,
    T_HOURS, T_PROPERTY, T_EMOTION, T_RULE, T_TAG, T_COLOR, T_ICON,
)

#: Человекочитаемые названия типов элементов
TYPE_LABELS = {
    T_CARD: "Карты",
    T_RESOURCE: "Ресурсы",
    T_ASPECT: "Аспекты",
    T_INFLUENCE: "Влияния",
    T_ELEMENT: "Элементы",
    T_SUPPRESSION: "Склонности",
    T_HOURS: "Часы",
    T_PROPERTY: "Свойства",
    T_EMOTION: "Эмоции",
    T_RULE: "Правила",
    T_TAG: "Теги",
    T_COLOR: "Цвета",
    T_ICON: "Иконки",
}

#: Подтипы карт (Type of card в Cultist Simulator)
CARD_SUBTYPES = ("Any", "Tool", "Lore", "Loan", "Margin", "Ingredient",
                 "Benefactor", "Foe", "Location")

#: Скалярные атрибуты карты: name -> spec
CARD_SCALARS: Dict[str, Dict[str, Any]] = {
    "name":        {"kind": "str",  "label": "Название"},
    "description": {"kind": "str",  "label": "Описание"},
    "flavor":      {"kind": "str",  "label": "Flavor-текст"},
    "subtype":     {"kind": "enum", "label": "Подтип", "values": CARD_SUBTYPES},
    "level":       {"kind": "int",  "label": "Уровень (Secret Levels)"},
    "weight":      {"kind": "int",  "label": "Вес (Weight)"},
    "border":      {"kind": "int",  "label": "Рамка (0..3)"},
    "reverse":     {"kind": "bool", "label": "Обратная сторона"},
    "color":       {"kind": "color_ref", "label": "Цвет карты"},
    "icon":        {"kind": "icon_ref",  "label": "Иконка"},
}

#: Списочные атрибуты карты: key -> spec
CARD_LISTS: Dict[str, Dict[str, Any]] = {
    "aspects":      {"target": T_ASPECT,     "unique": True,  "label": "Аспекты"},
    "tags":         {"target": T_TAG,        "unique": True,  "label": "Теги"},
    "elements":     {"target": T_ELEMENT,    "unique": True,  "label": "Элементы (Element)"},
    "influences":   {"target": T_INFLUENCE,  "unique": True,  "label": "Влияния"},
    "resources":    {"target": T_RESOURCE,   "unique": False, "store": "count",
                     "label": "Ресурсы (Materials)"},
    "suppressions": {"target": T_SUPPRESSION, "unique": False, "store": "count",
                     "label": "Склонности (Suppressions)"},
    "hours":        {"target": T_HOURS,      "unique": False, "store": "count",
                     "label": "Часы (Hours)"},
    "properties":   {"target": T_PROPERTY,   "unique": False, "store": "stacks",
                     "label": "Свойства (Properties)"},
    "emotions":     {"target": T_EMOTION,    "unique": False, "store": "count",
                     "label": "Эмоции / состояния"},
    "rules":        {"target": T_RULE,       "unique": True,  "label": "Правила (Rules)"},
}

#: Связи между картами: key -> spec
CARD_LINKS: Dict[str, Dict[str, Any]] = {
    "used_in":   {"label": "Используется в (Used in)", "direction": "up"},
    "produces":  {"label": "Порождает (Produces)",    "direction": "down"},
    "requires":  {"label": "Требует (Requires)",      "direction": "up"},
    "reflects":  {"label": "Отражает (Reflects)",     "direction": "self"},
    "alter_ego": {"label": "Альтер эго (Alter Ego)",  "direction": "self"},
}

#: Поля правила трансмутации (Transmutation Rules)
RULE_FIELDS: List[Tuple[str, str]] = [
    ("inputs",        "Ингредиенты"),
    ("aspect",        "Аспект действия"),
    ("duration",      "Длительность"),
    ("result",        "Результат"),
    ("additional",    "Дополнительно"),
    ("alternative",   "Альтернативный результат"),
    ("edge_failure",  "Крайний провал"),
    ("failure",       "Провал"),
    ("danger",        "Опасность"),
]


def default_card() -> Dict[str, Any]:
    """Карта по умолчанию со всеми пустыми атрибутами."""
    card: Dict[str, Any] = {"type": T_CARD, "slug": "", "schema": SCHEMA_VERSION}
    for k, spec in CARD_SCALARS.items():
        if spec["kind"] == "int":
            card[k] = 0
        elif spec["kind"] == "bool":
            card[k] = False
        else:
            card[k] = ""
    for k in CARD_LISTS:
        card[k] = []
    for k in CARD_LINKS:
        card[k] = []
    card["transmutations"] = {}          # имя правила -> dict RULE_FIELDS
    return card


def default_element(etype: str) -> Dict[str, Any]:
    """Пустой элемент заданного типа."""
    e: Dict[str, Any] = {"type": etype, "slug": "", "name": ""}
    if etype == T_RESOURCE:
        e.update({"description": "", "flavor": "", "icon": "", "color": "",
                  "tags": [], "properties": []})
    elif etype == T_ASPECT:
        e.update({"description": "", "keywords": []})
    elif etype == T_INFLUENCE:
        e.update({"description": "", "keywords": []})
    elif etype == T_ELEMENT:
        e.update({"description": ""})
    elif etype == T_SUPPRESSION:
        e.update({"weakens": "", "description": ""})
    elif etype == T_HOURS:
        e.update({"description": "", "keywords": []})
    elif etype == T_PROPERTY:
        e.update({"description": "", "stackable": False})
    elif etype == T_EMOTION:
        e.update({"description": "", "source": ""})
    elif etype == T_RULE:
        e.update({k: "" for k, _ in RULE_FIELDS})
    elif etype == T_TAG:
        e.update({"description": ""})
    elif etype == T_COLOR:
        e.update({"hex": "#000000", "description": ""})
    elif etype == T_ICON:
        e.update({"glyph": "?", "description": ""})
    return e


# ---------------------------------------------------------------------------
# Slug / id
# ---------------------------------------------------------------------------
_TRANS = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def slugify(text: str, maxlen: int = 48) -> str:
    """Транслитерирует и превращает текст в безопасное имя файла/slug.

    Сначала убирается «йотация» (мя->ma, лья->lia, ь/ъ отбрасываются),
    затем остаток транслитерируется по таблице ``_TRANS``.
    """
    t = unicodedata.normalize("NFKD", deyo((text or "").strip().lower()))
    t = t.translate(_TRANS)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if not t:
        t = "item"
    return t[:maxlen].rstrip("-") or "item"


def ensure_unique_slug(base: str, taken) -> str:
    base = slugify(base)
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


# ---------------------------------------------------------------------------
# Нормализация / валидация
# ---------------------------------------------------------------------------
def is_ref(item: Any) -> bool:
    return isinstance(item, dict) and "ref" in item


def ref_of(item: Any) -> str:
    if isinstance(item, dict):
        return item.get("ref", "")
    return str(item)


def count_of(item: Any, store: str = "count") -> int:
    try:
        return max(1, int(item.get(store, 1)))
    except Exception:
        return 1


def normalize_list(raw: Any) -> List[Dict[str, Any]]:
    """Приводит список элементов карты к каноническому виду ссылок."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if isinstance(it, str):
            out.append({"ref": it})
        elif isinstance(it, dict):
            out.append(copy.deepcopy(it))
    return out


def validate_card(card: Dict[str, Any], known_refs: Optional[set] = None) -> List[str]:
    """Возвращает список предупреждений по карте (не блокирующий)."""
    warns: List[str] = []
    if not card.get("name"):
        warns.append("У карты пустое название")
    if known_refs is not None:
        for key, spec in CARD_LISTS.items():
            for item in card.get(key, []):
                if is_ref(item):
                    r = ref_of(item)
                    if r and r not in known_refs:
                        warns.append(f"{spec['label']}: ссылка '{r}' отсутствует в базе")
    for key, spec in CARD_LISTS.items():
        if spec["unique"]:
            seen = set()
            for item in card.get(key, []):
                r = ref_of(item)
                if r in seen:
                    warns.append(f"{spec['label']}: дубликат '{r}' (уникальный атрибут)")
                seen.add(r)
    return warns


# ---------------------------------------------------------------------------
# Категории (древовидная структура) / наборы
# ---------------------------------------------------------------------------
def category_path_to_id(path: List[str]) -> str:
    """['Карты', 'Лор'] -> 'karty__lor' (безопасные имена каталогов)."""
    parts = [slugify(p, 40) for p in path if p]
    return "__".join(parts)


def new_category(cid: str, title: str, parent: str = "") -> Dict[str, Any]:
    return {"id": cid, "title": title, "parent": parent}


def new_set(sid: str, title: str, category: str, element_type: str) -> Dict[str, Any]:
    return {"id": sid, "title": title, "category": category, "type": element_type}
