# -*- coding: utf-8 -*-
"""Заполнение базы демонстрационными данными в стиле Cultist Simulator."""
from __future__ import annotations

from typing import Any, Dict

from . import schema as S
from .storage import Database


def _card(name: str, **kw: Any) -> Dict[str, Any]:
    c = S.default_card()
    c["name"] = name
    for k, v in kw.items():
        if k in c:
            if isinstance(c[k], list):
                c[k] = [dict(x) for x in v]
            else:
                c[k] = v
    return c


def seed(db: Database) -> None:
    """Создаёт дерево категорий, наборы и элементы (если база пуста)."""
    if db.categories or db.sets:
        return

    # ---- категории -----------------------------------------------------
    root_cards = db.create_category("Карты")
    cards_main = db.create_category("Основные", root_cards)
    cards_dlc = db.create_category("Дополнения", root_cards)
    history_c = db.create_category("История", cards_dlc)   # глубокая подкатегория

    attrs = db.create_category("Атрибуты")
    aspects_c = db.create_category("Аспекты", attrs)
    influences_c = db.create_category("Влияния", attrs)
    resources_c = db.create_category("Ресурсы", attrs)
    properties_c = db.create_category("Свойства", attrs)
    tags_c = db.create_category("Теги", attrs)
    colors_c = db.create_category("Цвета и иконки", attrs)

    # ---- наборы (один тип элементов на файл) ---------------------------
    set_cards = db.create_set("Стартовые карты", cards_main, S.T_CARD)
    set_hist = db.create_set("Исторические карты", history_c, S.T_CARD)
    set_aspects = db.create_set("Базовые аспекты", aspects_c, S.T_ASPECT)
    set_inf = db.create_set("Влияния", influences_c, S.T_INFLUENCE)
    set_res = db.create_set("Материалы", resources_c, S.T_RESOURCE)
    set_prop = db.create_set("Свойства", properties_c, S.T_PROPERTY)
    set_tags = db.create_set("Теги", tags_c, S.T_TAG)
    set_col = db.create_set("Палитра", colors_c, S.T_COLOR)
    set_icons = db.create_set("Иконки", colors_c, S.T_ICON)

    # ---- переиспользуемые атрибуты -------------------------------------
    aspects = {
        "lye": "Жертва (Lye)", "divide": "Разделение (Divide)",
        "forge": "Кузнец (Forge)", "knock": "Стук (Knock)",
        "mordant": "Трагедия (Mordant)", "nectar": "Нектар (Nectar)",
        "principle": "Принцип (Principle)", "secret-histories": "Тайные истории",
        "winter": "Зима (Winter)", "lore": "Лор", "danger": "Опасность",
        "edge": "Край (Edge)", "ruin": "Разрушение (Ruin)",
    }
    for slug, title in aspects.items():
        db.add_element(set_aspects, {"slug": slug, "name": title,
                                     "description": "", "keywords": []})

    influences = {"moon": "Луна (Moon)", "dawn": "Рассвет (Dawn)",
                  "winter-i": "Зима (Winter)", "spring": "Весна (Spring)",
                  "hour": "Час (Hour)"}
    for slug, title in influences.items():
        db.add_element(set_inf, {"slug": slug, "name": title,
                                 "description": "", "keywords": []})

    resources = ["fear", "health", "reason", "passion", "groat", "fuel",
                 "spirit", "dread"]
    res_titles = {"fear": "Страх (Fear)", "health": "Здоровье (Health)",
                  "reason": "Рассудок (Reason)", "passion": "Страсть (Passion)",
                  "groat": "Гроут (Groat)", "fuel": "Топливо (Fuel)",
                  "spirit": "Дух (Spirit)", "dread": "Ужас (Dread)"}
    for slug in resources:
        db.add_element(set_res, {"slug": slug, "name": res_titles[slug],
                                "description": "", "flavor": "",
                                "icon": "", "color": "", "tags": [],
                                "properties": []})

    properties = {"unreliable": "Ненадёжность (Unreliable)",
                  "ineffable": "Невыразимость (Ineffable)",
                  "bound": "Связанность (Bound)",
                  "reflective": "Отражаемость (Reflective)"}
    for slug, title in properties.items():
        db.add_element(set_prop, {"slug": slug, "name": title,
                                  "description": "", "stackable": True})

    tags = {"start": "Стартовая", "tool": "Инструмент", "lorecard": "Лор-карта",
            "crucible": "Тигель"}
    for slug, title in tags.items():
        db.add_element(set_tags, {"slug": slug, "name": title, "description": ""})

    colors = {"civilized": ("Цивилизованный", "#c8b47a"),
              "wild": ("Дикий", "#6f8f5a"), "dark": ("Тёмный", "#3a3a4a"),
              "gold": ("Золото", "#d4af37")}
    for slug, (title, hx) in colors.items():
        db.add_element(set_col, {"slug": slug, "name": title, "hex": hx,
                                 "description": ""})

    icons = {"sun": ("Солнце", "☀"), "moon": ("Луна", "☾"),
             "key": ("Ключ", "⚷"), "chalice": ("Чаша", "🍷")}
    for slug, (title, g) in icons.items():
        db.add_element(set_icons, {"slug": slug, "name": title, "glyph": g,
                                   "description": ""})

    # ---- карты ----------------------------------------------------------
    groat = _card("Гроут (Groat)",
                  description="Валюта Империи. Пахнет пылью и чужими тайнами.",
                  flavor="«Каждая монета помнит руку, что её держала.»",
border=0,
                  color="civilized", icon="sun",
                  aspects=[{"ref": "nectar"}],
                  elements=[{"ref": "lye"}],
                  tags=[{"ref": "start"}],
                  resources=[{"ref": "groat", "count": 1}],
                  used_in=[])
    slug_groat = db.add_element(set_cards, groat)

    fund = _card("Финансирование перевода",
                 description="Перевод сомнительного текста о сновидениях.",
                 flavor="Язык оригинала знает больше, чем автор.",
border=1,
                 color="dark", icon="key",
                 aspects=[{"ref": "secret-histories"}, {"ref": "principle"}],
                 influences=[{"ref": "moon"}],
                 resources=[{"ref": "groat", "count": 2},
                            {"ref": "spirit", "count": 1}],
                 suppressions=[{"ref": "fear", "count": 1}],
                 properties=[{"ref": "unreliable", "stacks": 1}],
                 requires=[],
                 produces=[],
                 transmutations={
                     "Перевод": {"inputs": "Финансирование + Гроут",
                                 "aspect": "Тайные истории",
                                 "duration": "Долго",
                                 "result": "Книга снов",
                                 "additional": "Знание",
                                 "alternative": "", "edge_failure": "",
                                 "failure": "Пепел", "danger": ""}})
    slug_fund = db.add_element(set_cards, fund)

    book = _card("Книга снов (Book of Dreams)",
                 description="Том, который читает вас в ответ.",
                 flavor="На полях — заметки, которых не мог оставить переводчик.",
border=2,
                 color="dark", icon="moon",
                 aspects=[{"ref": "secret-histories"}, {"ref": "winter"}],
                 influences=[{"ref": "moon"}, {"ref": "hour"}],
                 emotions=[{"ref": "dread", "count": 1}],
                 properties=[{"ref": "ineffable", "stacks": 2}],
                 tags=[{"ref": "lorecard"}],
                 reflects=[])
    slug_book = db.add_element(set_cards, book)

    knock = _card("Стук в дверь (Knock)",
                  description="Кто-то пришёл. Кто-то всегда приходит.",
                  flavor="Три удара. Пауза. Ещё два.",
border=1,
                  color="wild", icon="chalice",
                  aspects=[{"ref": "knock"}, {"ref": "danger"}],
                  influences=[{"ref": "dawn"}],
                  resources=[{"ref": "fear", "count": 2}],
                  used_in=[])
    slug_knock = db.add_element(set_hist, knock)

    # связи заполняем после того, как известны реальные slug'и карт
    def _link(slug, key, targets):
        items = db.get_elements(slug_set_of(slug))
        it = items[slug]
        it[key] = [{"ref": t} for t in targets if t in items]
        db.save_set(slug_set_of(slug))

    cards_sets = [set_cards, set_hist]
    def slug_set_of(slug):
        for ss in cards_sets:
            if slug in db.get_elements(ss):
                return ss
        return set_cards

    _link(slug_groat, "used_in", [slug_fund])
    _link(slug_fund, "requires", [slug_groat])
    _link(slug_fund, "produces", [slug_book])
    _link(slug_book, "reflects", [slug_fund])
    _link(slug_knock, "used_in", [slug_book])
    db.save()
