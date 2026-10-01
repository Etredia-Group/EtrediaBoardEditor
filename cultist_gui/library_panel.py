# -*- coding: utf-8 -*-
"""Панель библиотеки переиспользуемых атрибутов — источник Drag&Drop.

Элементы отсортированы по типам; их можно перетаскивать на соответствующие
drop-зоны в конструкторе карты.  Двойной клик открывает редактор элемента,
кнопка «+» создаёт новый атрибут выбранного типа.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from cultist_db import schema as S
from cultist_db.storage import Database

from .widgets import (DND_ELEMENT, ensure_drag_source, make_payload,
                      new_element_dialog)

#: типы, доступные в библиотеке (карты живут в дереве слева)
LIB_TYPES = [S.T_ASPECT, S.T_INFLUENCE, S.T_ELEMENT, S.T_RESOURCE,
             S.T_SUPPRESSION, S.T_HOURS, S.T_PROPERTY, S.T_EMOTION,
             S.T_RULE, S.T_TAG, S.T_COLOR, S.T_ICON]


class LibraryPanel(ttk.Frame):
    def __init__(self, master, db: Database, on_changed=None):
        super().__init__(master)
        self.db = db
        self.on_changed = on_changed
        self._drag_payload: Optional[str] = None

        top = ttk.Frame(self); top.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(top, text="Библиотека атрибутов").pack(side="left")
        ttk.Button(top, text="+ новый", width=9,
                   command=self._new_element).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tabs = {}
        for t in LIB_TYPES:
            f = ttk.Frame(self.nb)
            vsb = ttk.Scrollbar(f)
            lst = tk.Listbox(f, activestyle="dotbox",
                             yscrollcommand=vsb.set, exportselection=False)
            vsb.config(command=lst.yview)
            lst.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            lst.bind("<<ListboxSelect>>", lambda e, l=lst: self._remember(l))
            lst.bind("<Double-1>", lambda e, tt=t: self._edit(tt))
            # drag source (регистрируется один раз; TkDND сам активирует
            # перетаскивание при движении ЛКМ по выделенной строке)
            try:
                if ensure_drag_source(lst):
                    lst.dnd_bind("<<DragInitCmd>>",
                                 lambda e, l=lst, tt=t: self._drag_init(l, tt))
            except Exception:
                pass
            self.nb.add(f, text=S.TYPE_LABELS[t])
            self.tabs[t] = lst
        self._current_type = S.T_ASPECT
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.refresh()

    # ------------------------------------------------------------- данные
    def _tab_changed(self, _e):
        idx = self.nb.index(self.nb.select())
        self._current_type = LIB_TYPES[idx]

    def refresh(self):
        for t, lst in self.tabs.items():
            sel = lst.curselection()
            keep = lst.get(sel[0]) if sel else None
            lst.delete(0, "end")
            for sid, slug, it in self.db.iter_elements(t):
                name = it.get("name", slug)
                extra = ""
                if t == S.T_COLOR and it.get("hex"):
                    extra = f"  [{it['hex']}]"
                elif t == S.T_ICON and it.get("glyph"):
                    extra = f"  [{it['glyph']}]"
                elif t == S.T_SUPPRESSION and it.get("weakens"):
                    extra = f"  ⊣ {it['weakens']}"
                lst.insert("end", f"{name}  ({slug}){extra}")
                if keep and lst.get("end") == keep:
                    lst.selection_set("end")
            if not lst.size():
                lst.insert("end", "— пусто: создайте элемент кнопкой «+ новый» —")

    def _element_at(self, t):
        lst = self.tabs[t]
        sel = lst.curselection()
        if not sel:
            return None
        txt = lst.get(sel[0])
        # извлекаем slug из "(slug)" перед доп. полями
        i = txt.rfind("(")
        j = txt.rfind(")")
        slug = txt[i + 1:j] if 0 <= i < j else ""
        found = self.db.find_element(slug, t)
        return (sid, slug, it) if found else None

    # ------------------------------------------------------------- drag
    def _drag_init(self, lst, t):
        sel = lst.curselection()
        if not sel:
            return ("NONE", "none", "")
        found = self._element_at(t)
        if not found:
            return ("NONE", "none", "")
        _sid, slug, it = found
        payload = make_payload("element", etype=t, slug=slug,
                               name=it.get("name", slug))
        return (DND_ELEMENT, "copy", payload)

    # ------------------------------------------------------------- CRUD
    def _remember(self, lst):
        pass

    def _new_element(self):
        res = new_element_dialog(self, self.db, self._current_type)
        if res:
            self.refresh()
            if self.on_changed:
                self.on_changed()

    def _edit(self, t):
        found = self._element_at(t)
        if not found:
            return
        sid, slug, _it = found
        from .tree_panel import ElementEditDialog
        dlg = ElementEditDialog(self, self.db, sid, slug)
        self.wait_window(dlg)
        self.refresh()
        if self.on_changed:
            self.on_changed()
