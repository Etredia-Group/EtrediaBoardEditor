# -*- coding: utf-8 -*-
"""Вспомогательные виджеты GUI: drag&drop-обёртки, диалоги выбора элементов.

DnD работает через tkinterdnd2 (Tk DND), если он доступен; иначе приложения
 gracefully деградируют до кнопок «Добавить/Удалить» и перетаскивание
 внутри списков через кнопки ▲▼.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, simpledialog
from typing import Any, Callable, Dict, List, Optional, Tuple

from cultist_db import schema as S

try:                                     # pragma: no cover
    from tkinterdnd2 import TkinterDnD, DND_FILES  # noqa: F401
    HAS_DND = True
except Exception:                        # pragma: no cover
    HAS_DND = False

#: MIME-подобный тип для внутренних перетаскиваний элементов базы
DND_ELEMENT = "APPLICATION/CARTELEMENT"

# ---------------------------------------------------------------------------
# Единый интерфейс регистрации drop-target
# ---------------------------------------------------------------------------


def register_drop(widget, handler: Callable[[str], None],
                  types=(DND_ELEMENT,)) -> bool:
    """Регистрирует widget как приёмник DnD; handler получает payload-строку.

    Возвращает True, если регистрация удалась.
    """
    if not HAS_DND:
        return False
    try:
        widget.drop_target_register(*types)
        widget.dnd_bind("<<Drop>>", lambda ev: handler(ev.data))
        return True
    except Exception:
        return False


def ensure_drag_source(widget) -> bool:
    """Однократная регистрация виджета как источника перетаскивания."""
    if not HAS_DND or getattr(widget, "_is_drag_source", False):
        return getattr(widget, "_is_drag_source", False)
    try:
        widget.drag_source_register(1, DND_ELEMENT)
        widget._is_drag_source = True
        return True
    except Exception:
        return False


def dnd_available() -> bool:
    return HAS_DND


# ---------------------------------------------------------------------------
# Payload-форматы
# ---------------------------------------------------------------------------

def make_payload(kind: str, **kw) -> str:
    """kind: 'element' | 'set' | 'category' | 'cardref'."""
    p = {"kind": kind}
    p.update(kw)
    return json.dumps(p, ensure_ascii=False)


def parse_payload(data: str) -> Optional[dict]:
    try:
        p = json.loads(data.strip())
        if isinstance(p, dict):
            return p
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Диалог выбора элемента из базы (по типу)
# ---------------------------------------------------------------------------

class ElementPicker(tk.Toplevel):
    """Список всех элементов заданного типа с поиском; возвращает slug+item."""

    def __init__(self, master, db, etype: str, title: str = "",
                 multi: bool = False):
        super().__init__(master)
        self.db = db
        self.etype = etype
        self.multi = multi
        self.result: List[Dict[str, Any]] = []
        self.title(title or f"Выбор: {S.TYPE_LABELS.get(etype, etype)}")
        self.geometry("460x420")
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=6)
        frm.pack(fill="both", expand=True)
        self.var_search = tk.StringVar()
        e = ttk.Entry(frm, textvariable=self.var_search)
        e.pack(fill="x")
        e.bind("<KeyRelease>", lambda _ev: self._fill())
        e.focus_set()

        cols = ("name", "slug", "set")
        self.tree = ttk.Treeview(frm, columns=cols, show="tree headings",
                                 selectmode="extended" if multi else "browse")
        self.tree.heading("#0", text="Элемент")
        self.tree.column("#0", width=170)
        for c, lbl, w in (("name", "Название", 150), ("slug", "Slug", 110),
                          ("set", "Набор", 120)):
            self.tree.heading(c, text=lbl)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<Double-1>", lambda _ev: self._ok())

        bf = ttk.Frame(frm)
        bf.pack(fill="x")
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)
        self._fill()

    def _fill(self):
        q = self.var_search.get().lower()
        self.tree.delete(*self.tree.get_children())
        for sid, slug, it in self.db.iter_elements(self.etype):
            st = self.db.sets[sid]["title"]
            name = it.get("name", slug)
            hay = f"{name} {slug} {st}".lower()
            if q and q not in hay:
                continue
            self.tree.insert("", "end", iid=f"{sid}|{slug}", text=st.split("/")[-1],
                             values=(name, slug, st))

    def _ok(self):
        out = []
        for iid in self.tree.selection():
            sid, slug = iid.split("|", 1)
            it = self.db.get_elements(sid).get(slug)
            if it is not None:
                out.append({"sid": sid, "slug": slug, "item": it})
        if out:
            self.result = out
            self.destroy()


def pick_element(master, db, etype: str, multi: bool = False) -> List[dict]:
    dlg = ElementPicker(master, db, etype, multi=multi)
    master.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Диалог создания нового переиспользуемого элемента
# ---------------------------------------------------------------------------

class NewElementDialog(tk.Toplevel):
    """Создаёт элемент заданного типа в выбранном наборе (или новом наборе)."""

    def __init__(self, master, db, etype: str, preset_name: str = ""):
        super().__init__(master)
        self.db = db
        self.etype = etype
        self.result: Optional[Tuple[str, str]] = None  # (sid, slug)
        self.title(f"Новый элемент: {S.TYPE_LABELS.get(etype, etype)}")
        self.geometry("430x330")
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)
        r = 0
        ttk.Label(frm, text="Название:").grid(row=r, column=0, sticky="w")
        self.var_name = tk.StringVar(value=preset_name)
        ttk.Entry(frm, textvariable=self.var_name, width=40).grid(
            row=r, column=1, sticky="we"); r += 1

        ttk.Label(frm, text="Описание:").grid(row=r, column=0, sticky="n w")
        self.txt_desc = tk.Text(frm, height=3, width=40)
        self.txt_desc.grid(row=r, column=1, sticky="we"); r += 1

        # дополнительные поля по типу
        self.extra: Dict[str, tk.Variable] = {}
        extra_fields = {
            S.T_COLOR: [("hex", "HEX-цвет", "#c8a24b")],
            S.T_ICON: [("glyph", "Глиф/имя файла", "★")],
            S.T_SUPPRESSION: [("weakens", "Ослабляет (slug аспекта)", "")],
            S.T_PROPERTY: [("stackable", "Стекируется (bool)", "")],
        }.get(etype, [])
        for key, label, dv in extra_fields:
            ttk.Label(frm, text=label + ":").grid(row=r, column=0, sticky="w")
            v = tk.StringVar(value=dv)
            ttk.Entry(frm, textvariable=v, width=40).grid(
                row=r, column=1, sticky="we")
            self.extra[key] = v
            r += 1

        ttk.Label(frm, text="Набор:").grid(row=r, column=0, sticky="w")
        self.cb_set = ttk.Combobox(frm, state="readonly", width=36)
        self._fill_sets(); r += 1

        ttk.Label(frm, text="Категория набора:").grid(row=r, column=0, sticky="w")
        self.cb_cat = ttk.Combobox(frm, state="readonly", width=36)
        self._fill_cats()
        self.cb_cat.bind("<<ComboboxSelected>>", lambda _e: self._fill_sets())
        r += 1

        frm.columnconfigure(1, weight=1)
        bf = ttk.Frame(frm)
        bf.grid(row=r, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(bf, text="Создать", command=self._ok).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)
        self.var_name.focus_set()

    def _cat_list(self):
        self._cats: List[str] = []
        out: List[str] = []

        def walk(parent, depth):
            for c in self.db.category_children(parent):
                out.append("    " * depth + c["title"])
                self._cats.append(c["id"])
                walk(c["id"], depth + 1)

        walk("", 0)
        return out

    def _fill_cats(self):
        vals = self._cat_list()
        self.cb_cat["values"] = vals
        if vals:
            self.cb_cat.current(0)

    def _fill_sets(self):
        idx = self.cb_cat.current()
        cid = self._cats[idx] if 0 <= idx < len(self._cats) else ""
        names, ids = ["(новый набор в этой категории)"], ["__new__"]
        for st in self.db.sets_in_category(cid):
            if st["type"] == self.etype:
                names.append(st["title"]); ids.append(st["id"])
        self._set_ids = ids
        self.cb_set["values"] = names
        self.cb_set.current(0)

    def _ok(self):
        name = self.var_name.get().strip()
        if not name:
            return
        item = S.default_element(self.etype)
        item["name"] = name
        item["description"] = self.txt_desc.get("1.0", "end").strip()
        for k, v in self.extra.items():
            val = v.get().strip()
            if k == "stackable":
                item[k] = val.lower() in ("1", "true", "да", "yes")
            elif val:
                item[k] = val
        idx = self.cb_set.current()
        sid = self._set_ids[idx]
        if sid == "__new__":
            cat_idx = self.cb_cat.current()
            cid = self._cats[cat_idx]
            sid = self.db.create_set(S.TYPE_LABELS.get(self.etype, self.etype),
                                     cid, self.etype)
        slug = self.db.add_element(sid, item)
        self.result = (sid, slug)
        self.destroy()


def new_element_dialog(master, db, etype: str, preset_name: str = ""):
    dlg = NewElementDialog(master, db, etype, preset_name)
    master.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Простой prompt с валидацией
# ---------------------------------------------------------------------------

def ask_title(master, title: str, initial: str = "") -> Optional[str]:
    t = simpledialog.askstring(title, "Название:", initialvalue=initial,
                               parent=master)
    return (t or "").strip() or None
