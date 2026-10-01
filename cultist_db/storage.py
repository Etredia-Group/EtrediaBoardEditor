# -*- coding: utf-8 -*-
"""JSON-хранилище с древовидными категориями и наборами (sets).

Структура на диске::

    <root>/
        _index.json                 # категории + наборы (зеркало дерева)
        karty/                      # категория «Карты»
            _cat.json               # метаданные категории
            osnovnye/               # подкатегория «Основные»
                _cat.json
                set-01.json         # набор карт  (один тип элементов в файле)
                set-dop.json
        resursy/
            materialy.json          # набор ресурсов

Инварианты:
* один набор = один JSON-файл = один тип элементов;
* категория = каталог, подкатегория = вложенный каталог;
* при переименовании категории переименовывается и каталог (рекурсивно);
* операции над элементами используют ссылки {"ref": slug}.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import schema as S


class StorageError(Exception):
    pass


def title_ok(t: str) -> bool:
    return bool((t or "").strip())


class Database:
    """Менеджер JSON-базы: дерево категорий -> наборы -> элементы."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.index_path = os.path.join(self.root, "_index.json")
        self.categories: Dict[str, Dict[str, Any]] = {}   # cid -> cat dict
        self.sets: Dict[str, Dict[str, Any]] = {}         # sid -> set dict
        self._elements_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.dirty_sets: set = set()
        self.load()

    # ------------------------------------------------------------------ I/O
    def load(self) -> None:
        if os.path.isfile(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.categories = {c["id"]: c for c in data.get("categories", [])}
            self.sets = {s["id"]: s for s in data.get("sets", [])}
        else:
            self.categories, self.sets = {}, {}
        self._elements_cache.clear()
        self._scan_disk()
        self._reconcile_with_disk()

    # -------------------------------------------------- сканирование диска
    def _scan_disk(self) -> None:
        """Читает дерево категорий и наборы прямо с диска.

        Диск является авторитетным источником структуры: _cat.json задаёт
        id/заголовок/родителя категории, файлы наборов — свою категорию и тип.
        Это делает переименование каталогов безопасным даже при частичной
        записи индекса.
        """
        if not os.path.isdir(self.root):
            return
        found_cats: Dict[str, Dict[str, Any]] = {}
        for dirpath, dirnames, files in os.walk(self.root):
            if "_cat.json" not in files:
                continue
            try:
                with open(os.path.join(dirpath, "_cat.json"), "r",
                          encoding="utf-8") as f:
                    cat = json.load(f)
                cid = cat.get("id") or os.path.basename(dirpath)
                cat = dict(cat)
                cat["id"] = cid
                rel = os.path.relpath(dirpath, self.root)
                parent_dir = os.path.dirname(rel)
                pdir_id = "" if parent_dir == "." else os.path.basename(parent_dir)
                # родитель = категория, чей каталог непосредственно содержит этот
                cat["parent"] = "" if parent_dir == "." else pdir_id
                found_cats[cid] = cat
            except Exception:
                continue
        # согласование: берём заголовки из индекса, если они свежее
        for cid, cat in found_cats.items():
            old_cat = self.categories.get(cid)
            if old_cat and old_cat.get("title") != cat.get("title"):
                # заголовок из _cat.json на диске приоритетнее (он обновляется
                # вместе с перемещением каталога)
                pass
        self.categories = found_cats
        # наборы: перечитываем файлы *.json (кроме _cat/_index)
        found_sets: Dict[str, Dict[str, Any]] = {}
        for dirpath, _dirs, files in os.walk(self.root):
            for fn in files:
                if not fn.endswith(".json") or fn in ("_cat.json", "_index.json"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        j = json.load(f)
                except Exception:
                    continue
                if not isinstance(j, dict) or "set" not in j:
                    continue
                sid = j["set"]
                st = {"id": sid, "title": j.get("title", sid),
                      "type": j.get("type", S.T_CARD)}
                # категория набора = ближайший родительский _cat.json
                d = dirpath
                while d and d != self.root and not os.path.isfile(
                        os.path.join(d, "_cat.json")):
                    d = os.path.dirname(d)
                cid = os.path.basename(d) if d != self.root else ""
                if cid in self.categories:
                    st["category"] = self.categories[cid]["id"]
                elif cid:
                    st["category"] = cid
                else:
                    st["category"] = ""
                found_sets[sid] = st
                self._elements_cache[sid] = j.get("items", {})
        # дополняем индекс тем, чего нет в памяти; помечаем изменённые
        merged = dict(found_sets)
        for sid, st in self.sets.items():
            if sid not in merged:
                merged[sid] = st
        self.sets = merged

    def save_index(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        data = {
            "schema": S.SCHEMA_VERSION,
            "categories": sorted(self.categories.values(), key=lambda c: c["id"]),
            "sets": sorted(self.sets.values(), key=lambda s: s["id"]),
        }
        self._write_json(self.index_path, data)

    def save(self) -> None:
        """Сохраняет индекс и все изменённые наборы."""
        self.save_index()
        for sid in list(self.dirty_sets):
            self.save_set(sid)
        self.dirty_sets.clear()

    def _write_json(self, path: str, obj: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)

    # ------------------------------------------------------ пути на диске
    def category_dir(self, cid: str) -> str:
        """Каталог категории = корень + цепочка id от родителя к потомку."""
        chain: List[str] = []
        cur: Optional[str] = cid
        guard = 0
        while cur and cur in self.categories and guard < 50:
            chain.append(cur)
            cur = self.categories[cur].get("parent") or ""
            guard += 1
        return os.path.join(self.root, *reversed(chain))

    def set_path(self, sid: str) -> str:
        st = self.sets.get(sid)
        if not st:
            raise StorageError(f"Набор {sid} не найден")
        return os.path.join(self.category_dir(st["category"]), f"{sid}.json")

    def _save_cat_meta(self, cid: str) -> None:
        d = self.category_dir(cid)
        os.makedirs(d, exist_ok=True)
        self._write_json(os.path.join(d, "_cat.json"), self.categories[cid])

    # --------------------------------------------------- сверка с диском
    def _reconcile_with_disk(self) -> None:
        """Создаёт отсутствующие каталоги/файлы, чистит висячие записи."""
        for cid in list(self.categories):
            self._save_cat_meta(cid)
        for sid in list(self.sets):
            p = self.set_path(sid)
            if not os.path.exists(p):
                self._write_set_file(sid)
        # удаляем файлы наборов, которых нет в индексе (кроме _cat/_index)
        for dirpath, _dirs, files in os.walk(self.root):
            for fn in files:
                if fn in ("_index.json", "_cat.json") or not fn.endswith(".json"):
                    continue
                sid = fn[:-5]
                if sid not in self.sets:
                    orphan = os.path.join(dirpath, fn)
                    try:
                        with open(orphan, "r", encoding="utf-8") as f:
                            j = json.load(f)
                        if isinstance(j, dict) and "set" in j:
                            os.remove(orphan)      # осиротевший файл набора
                    except Exception:
                        pass

    # --------------------------------------------------------- категории
    def category_children(self, parent: str = "") -> List[Dict[str, Any]]:
        return sorted((c for c in self.categories.values()
                       if (c.get("parent") or "") == parent),
                      key=lambda c: c["title"].lower())

    def category_path_titles(self, cid: str) -> List[str]:
        titles: List[str] = []
        cur: Optional[str] = cid
        while cur and cur in self.categories:
            titles.append(self.categories[cur]["title"])
            cur = self.categories[cur].get("parent") or ""
        return titles[::-1]

    def create_category(self, title: str, parent: str = "") -> str:
        title = (title or "").strip()
        if not title:
            raise StorageError("Название категории не может быть пустым")
        taken = {c["id"] for c in self.categories.values()
                 if (c.get("parent") or "") == parent}
        cid = S.ensure_unique_slug(title, taken)
        self.categories[cid] = S.new_category(cid, title, parent)
        self._save_cat_meta(cid)
        self.save_index()
        return cid

    def rename_category(self, cid: str, new_title: str) -> None:
        """Переименовывает категорию и перестраивает пути каталогов на диске."""
        new_title = (new_title or "").strip()
        if not title_ok(new_title) or cid not in self.categories:
            raise StorageError("Некорректное переименование")
        parent = self.categories[cid].get("parent") or ""
        taken = {c["id"] for k, c in self.categories.items()
                 if (c.get("parent") or "") == parent and k != cid}
        new_id = S.ensure_unique_slug(new_title, taken)

        # старые физические пути (до изменения словаря)
        old_paths = {k: self.category_dir(k) for k in self.categories}

        # перестроение id потомков по префиксу
        prefix = cid + "__"
        mapping: Dict[str, str] = {cid: new_id}
        for k in list(self.categories):
            if k.startswith(prefix):
                mapping[k] = new_id + k[len(cid):]
        for k, v in mapping.items():
            cat = self.categories.pop(k)
            cat["id"] = v
            p = cat.get("parent") or ""
            cat["parent"] = mapping.get(p, p)
            self.categories[v] = cat
        self.categories[new_id]["title"] = new_title
        for st in self.sets.values():
            if st["category"] in mapping:
                st["category"] = mapping[st["category"]]

        # физическая миграция: переименовываемый каталог переносится
        # целиком вместе со всем поддерево (путом внутри управляет _cat.json)
        new_root = self.category_dir(new_id)
        if os.path.isdir(old_paths[cid]) and \
           os.path.abspath(old_paths[cid]) != os.path.abspath(new_root):
            if os.path.exists(new_root):
                shutil.rmtree(new_root, ignore_errors=True)
            os.makedirs(os.path.dirname(new_root), exist_ok=True)
            shutil.move(old_paths[cid], new_root)
        # после переноса — чистка устаревших физических путей потомков
        for k, v in mapping.items():
            if k == cid:
                continue
            oldp, newp = old_paths[k], self.category_dir(v)
            if os.path.abspath(oldp) != os.path.abspath(newp) and os.path.isdir(oldp):
                shutil.rmtree(oldp, ignore_errors=True)
        # финальная запись метаданных и файлов наборов по новым путям
        for v in mapping.values():
            d = self.category_dir(v)
            os.makedirs(d, exist_ok=True)
            self._save_cat_meta(v)
            for sid, st in self.sets.items():
                if st["category"] == v:
                    self._write_set_file(sid)
        self.save_index()

    def delete_category(self, cid: str, recursive: bool = False) -> None:
        if cid not in self.categories:
            return
        kids = [c["id"] for c in self.categories.values()
                if (c.get("parent") or "") == cid]
        if kids and not recursive:
            raise StorageError("Категория содержит подкатегории")
        sets_here = [s["id"] for s in self.sets.values() if s["category"] == cid]
        if sets_here and not recursive:
            raise StorageError("Категория содержит наборы")
        for sub in kids:
            self.delete_category(sub, recursive=True)
        for sid in sets_here:
            self.delete_set(sid)
        d = self.category_dir(cid)
        self.categories.pop(cid, None)
        self.save_index()
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------- наборы
    def sets_in_category(self, cid: str) -> List[Dict[str, Any]]:
        return sorted((s for s in self.sets.values() if s["category"] == cid),
                      key=lambda s: s["title"].lower())

    def create_set(self, title: str, category: str, element_type: str) -> str:
        title = (title or "").strip()
        if not title:
            raise StorageError("Название набора не может быть пустым")
        if category not in self.categories:
            raise StorageError("Категория не найдена")
        if element_type not in S.ELEMENT_TYPES:
            raise StorageError("Неизвестный тип элементов")
        taken = {s["id"] for s in self.sets.values()}
        sid = S.ensure_unique_slug(title, taken)
        self.sets[sid] = S.new_set(sid, title, category, element_type)
        self._write_set_file(sid)
        self.save_index()
        return sid

    def rename_set(self, sid: str, new_title: str) -> None:
        if sid not in self.sets:
            raise StorageError("Набор не найден")
        new_title = (new_title or "").strip()
        if not new_title:
            raise StorageError("Пустое название")
        old_path = self.set_path(sid)
        self.get_elements(sid)                     # гарантируем чтение кэша
        taken = {s["id"] for k, s in self.sets.items() if k != sid}
        new_id = S.ensure_unique_slug(new_title, taken)
        if sid in self._elements_cache:
            self._elements_cache[new_id] = self._elements_cache.pop(sid)
        st = self.sets.pop(sid)
        st["id"] = new_id
        st["title"] = new_title
        self.sets[new_id] = st
        self.dirty_sets.discard(sid)
        if os.path.exists(old_path):
            self._write_set_file(new_id)
            if old_path != self.set_path(new_id):
                os.remove(old_path)
        else:
            self._write_set_file(new_id)
        self.save_index()

    def delete_set(self, sid: str) -> None:
        if sid not in self.sets:
            return
        p = self.set_path(sid)
        self.sets.pop(sid, None)
        self._elements_cache.pop(sid, None)
        self.dirty_sets.discard(sid)
        self.save_index()
        if os.path.exists(p):
            os.remove(p)

    def move_set(self, sid: str, new_category: str) -> None:
        if sid not in self.sets or new_category not in self.categories:
            raise StorageError("Перемещение невозможно")
        old_path = self.set_path(sid)
        self.sets[sid]["category"] = new_category
        self._write_set_file(sid)
        if os.path.exists(old_path) and old_path != self.set_path(sid):
            os.remove(old_path)
        self.save_index()

    # ---------------------------------------------------------- элементы
    def _read_set_file(self, sid: str) -> Dict[str, Any]:
        p = self.set_path(sid)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    j = json.load(f)
                if isinstance(j, dict) and isinstance(j.get("items"), dict):
                    return j
            except Exception:
                pass
        return {"set": sid, "type": self.sets[sid]["type"],
                "title": self.sets[sid]["title"], "items": {}}

    def _write_set_file(self, sid: str) -> None:
        items = self._elements_cache.setdefault(sid, {})
        payload = {"set": sid, "type": self.sets[sid]["type"],
                   "title": self.sets[sid]["title"], "items": items}
        self._write_json(self.set_path(sid), payload)

    def get_elements(self, sid: str) -> Dict[str, Dict[str, Any]]:
        """Элементы набора (slug -> элемент). Лениво читает файл."""
        if sid not in self.sets:
            return {}
        if sid not in self._elements_cache:
            j = self._read_set_file(sid)
            self._elements_cache[sid] = j["items"]
        return self._elements_cache[sid]

    def add_element(self, sid: str, item: Dict[str, Any],
                    base_slug: Optional[str] = None) -> str:
        items = self.get_elements(sid)
        name = item.get("name", "")
        want = base_slug or item.get("slug") or name or "item"
        slug = S.ensure_unique_slug(want, set(items))
        it = dict(item)
        it["slug"] = slug
        it["type"] = self.sets[sid]["type"]
        items[slug] = it
        self.dirty_sets.add(sid)
        self.save_set(sid)
        return slug

    def update_element(self, sid: str, slug: str, item: Dict[str, Any]) -> None:
        items = self.get_elements(sid)
        if slug not in items:
            raise StorageError(f"Элемент {slug} не найден")
        it = dict(item)
        it["slug"] = slug
        it["type"] = self.sets[sid]["type"]
        items[slug] = it
        self.save_set(sid)

    def remove_element(self, sid: str, slug: str) -> None:
        items = self.get_elements(sid)
        if slug in items:
            del items[slug]
            self.save_set(sid)

    def save_set(self, sid: str) -> None:
        if sid in self.sets:
            self._write_set_file(sid)
            self.dirty_sets.discard(sid)

    # ----------------------------------------------- глобальный реестр
    def all_sets_of_type(self, etype: str) -> List[str]:
        return [s["id"] for s in sorted(self.sets.values(),
                                        key=lambda s: s["title"].lower())
                if s["type"] == etype]

    def find_element(self, slug: str,
                     etype: Optional[str] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Ищет элемент по slug во всех наборах (опционально заданного типа)."""
        for sid in self.sets:
            if etype and self.sets[sid]["type"] != etype:
                continue
            items = self.get_elements(sid)
            if slug in items:
                return sid, items[slug]
        return None

    def iter_elements(self, etype: str) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
        for sid in self.all_sets_of_type(etype):
            for slug, it in self.get_elements(sid).items():
                yield sid, slug, it

    def known_slugs(self, etypes: Optional[Iterable[str]] = None) -> set:
        out = set()
        for sid, st in self.sets.items():
            if etypes and st["type"] not in etypes:
                continue
            out.update(self.get_elements(sid).keys())
        return out

    def usage_count(self, slug: str, etype: str) -> int:
        """Сколько раз элемент используется в картах (по ссылкам)."""
        n = 0
        for sid, st in self.sets.items():
            if st["type"] != S.T_CARD:
                continue
            for card in self.get_elements(sid).values():
                for key, spec in S.CARD_LISTS.items():
                    if spec["target"] != etype:
                        continue
                    for item in card.get(key, []):
                        if S.is_ref(item) and S.ref_of(item) == slug:
                            n += 1
                for key in S.CARD_LINKS:
                    for item in card.get(key, []):
                        if S.ref_of(item) == slug:
                            n += 1
                for _rn, rule in (card.get("transmutations") or {}).items():
                    if isinstance(rule, dict) and slug in json.dumps(rule, ensure_ascii=False):
                        n += 1
        return n

    # ------------------------------------------------- promote / import
    def promote_new_items(self, card: Dict[str, Any],
                          target_set_by_type: Dict[str, str]) -> Dict[str, Any]:
        """Заменяет ``{"new": {...}}`` в списках карты на ссылки, создавая
        элементы в соответствующих наборах.  Возвращает обновлённую карту."""
        card = json.loads(json.dumps(card))  # deep copy через json
        for key, spec in S.CARD_LISTS.items():
            lst = card.get(key, [])
            out = []
            for item in lst:
                if isinstance(item, dict) and "new" in item:
                    etype = spec["target"]
                    sid = target_set_by_type.get(etype)
                    if not sid or sid not in self.sets:
                        # нет набора — оставляем как есть, но с ref-заглушкой
                        out.append({"ref": "", "unresolved_new": item["new"]})
                        continue
                    new_item = dict(item["new"])
                    new_item.setdefault("name", "Без имени")
                    slug = self.add_element(sid, new_item)
                    link = {"ref": slug}
                    store = spec.get("store")
                    if store and store in item:
                        link[store] = item[store]
                    out.append(link)
                else:
                    out.append(item)
            card[key] = out
        return card
