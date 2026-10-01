# -*- coding: utf-8 -*-
"""Левая панель: древовидный браузер базы (категории → наборы → элементы).

Поддерживает Drag&Drop:
* перетаскивание набора на категорию  -> move_set;
* перетаскивание элемента-атрибута на карту в конструкторе -> добавление;
* контекстные меню для CRUD категорий/наборов/элементов.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Dict, Optional

from cultist_db import schema as S
from cultist_db.storage import Database, StorageError

from .widgets import (ask_title, ensure_drag_source, make_payload,
                      new_element_dialog, parse_payload, pick_element,
                      register_drop)

# iid префиксы
P_CAT = "cat:"
P_SET = "set:"
P_ELM = "elm:"


class TreePanel(ttk.Frame):
    def __init__(self, master, db: Database,
                 on_card_open: Callable[[str, str], None]):
        super().__init__(master)
        self.db = db
        self.on_card_open = on_card_open
        self._popup_targets: tuple = ()

        vsb = ttk.Scrollbar(self)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse",
                                 yscrollcommand=vsb.set)
        vsb.config(command=self.tree.yview)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-3>", self._on_popup)
        self.tree.bind("<<TreeviewSelect>>", lambda e: None)
        # источник перетаскивания: наборы и атрибуты
        self._drag_iid: Optional[str] = None
        self.tree.bind("<B1-Motion>", self._maybe_drag)
        self.tree.bind("<ButtonRelease-1>", self._end_drag)
        register_drop(self.tree, self._on_drop_tree)

    def _end_drag(self, _ev):
        """После завершения перетаскивания отвязываем DragInitCmd, чтобы
        обычные клики не запускали новый drag (TkDND остаётся активным
        источником до снятии регистрации)."""
        if self._drag_iid is not None:
            self._drag_iid = None
            try:
                self.tree.dnd_bind("<<DragInitCmd>>",
                                   lambda e: ("NONE", "none", ""))
            except Exception:
                pass

    # ------------------------------------------------------------ заполнение
    def refresh(self, keep_selection: bool = True):
        sel = self.tree.selection()
        old = sel[0] if sel else None
        expanded = set()
        def walk(i):
            for c in self.tree.get_children(i):
                if self.tree.item(c, "open"):
                    expanded.add(c)
                    walk(c)
        walk("")
        self.tree.delete(*self.tree.get_children(""))
        self._insert_category("", "")
        def reopen(i):
            for c in self.tree.get_children(i):
                if c in expanded:
                    self.tree.item(c, open=True)
                    reopen(c)
        reopen("")
        if keep_selection and old and self.tree.exists(old):
            self.tree.selection_set(old)
            self.tree.see(old)

    def _insert_category(self, parent_iid: str, cid: str):
        if cid:
            cat = self.db.categories[cid]
            iid = P_CAT + cid
            n_sets = len(self.db.sets_in_category(cid))
            self.tree.insert(parent_iid, "end", iid=iid,
                             text=f"📁 {cat['title']}  [{n_sets}]",
                             tags=("category",))
        else:
            iid = ""
        # наборы категории
        for st in self.db.sets_in_category(cid):
            sid_iid = P_SET + st["id"]
            label = f"🗂 {st['title']} ({S.TYPE_LABELS.get(st['type'], st['type'])})"
            self.tree.insert(iid, "end", iid=sid_iid, text=label,
                             tags=("set", st["type"]))
            items = self.db.get_elements(st["id"])
            for slug, it in sorted(items.items(),
                                   key=lambda kv: kv[1].get("name", "").lower()):
                name = it.get("name", slug)
                icon = ""
                if st["type"] == S.T_CARD:
                    icon = "🃏"
                elif st["type"] == S.T_COLOR:
                    icon = "🎨"
                elif st["type"] == S.T_ICON:
                    icon = "✦"
                self.tree.insert(sid_iid, "end", iid=f"{P_ELM}{st['id']}|{slug}",
                                 text=f"{icon} {name}",
                                 tags=("element", st["type"], slug))
        # подкатегории
        for sub in self.db.category_children(cid):
            self._insert_category(iid or "", sub["id"])

    # ------------------------------------------------------------ действия
    def selected(self) -> tuple:
        """-> (kind, id, extra) по выделенному узлу."""
        sel = self.tree.selection()
        if not sel:
            return ("", "", "")
        iid = sel[0]
        if iid.startswith(P_CAT):
            return ("category", iid[len(P_CAT):], "")
        if iid.startswith(P_SET):
            return ("set", iid[len(P_SET):], "")
        if iid.startswith(P_ELM):
            sid, slug = iid[len(P_ELM):].split("|", 1)
            return ("element", sid, slug)
        return ("", "", "")

    def _on_double(self, _ev):
        kind, a, b = self.selected()
        if kind == "element":
            st = self.db.sets.get(a)
            if st and st["type"] == S.T_CARD:
                self.on_card_open(a, b)

    def _maybe_drag(self, ev):
        iid = self.tree.identify_row(ev.y)
        if not iid or iid == self._drag_iid:
            return
        draggable = (iid.startswith(P_SET)
                     or (iid.startswith(P_ELM)
                         and "card" not in self.tree.item(iid, "tags")))
        payload = self._payload_for(iid) if draggable else None
        if payload is None:
            # не drag-объект: снимаем активацию источника
            try:
                self.tree.dnd_activate(0)
            except Exception:
                pass
            return
        self._drag_iid = iid
        self.tree.selection_set(iid)
        try:
            if ensure_drag_source(self.tree):
                self.tree.dnd_bind("<<DragInitCmd>>",
                                   lambda e, p=payload: (DND_ELEMENT, "copy", p))
                self.tree.dnd_activate(1)
        except Exception:
            pass

    def _payload_for(self, iid: str) -> Optional[str]:
        if iid.startswith(P_SET):
            sid = iid[len(P_SET):]
            return make_payload("set", sid=sid)
        if iid.startswith(P_ELM):
            sid, slug = iid[len(P_ELM):].split("|", 1)
            stype = self.db.sets[sid]["type"]
            if stype == S.T_CARD:
                return make_payload("cardref", sid=sid, slug=slug)
            return make_payload("element", etype=stype, slug=slug, sid=sid)
        return None

    # drop наборов на категории
    def _on_drop_tree(self, data: str):
        p = parse_payload(data)
        if not p:
            return
        sel = self.tree.selection()
        tgt = sel[0] if sel else ""
        if p.get("kind") == "set" and tgt.startswith(P_CAT):
            cid = tgt[len(P_CAT):]
            try:
                self.db.move_set(p["sid"], cid)
            except StorageError as e:
                messagebox.showerror("Ошибка", str(e))
            self.refresh()

    # ------------------------------------------------------------- контекст
    def _on_popup(self, ev):
        iid = self.tree.identify_row(ev.y)
        if iid:
            self.tree.selection_set(iid)
            kind, a, b = self.selected()
        else:
            self.tree.selection_remove(*self.tree.selection())
            kind, a, b = "", "", ""
        m = tk.Menu(self.tree, tearoff=0)   # parent — сам treeview!
        if kind == "":
            m.add_command(label="Новая категория (в корне)",
                          command=lambda: self._new_category(""))
        elif kind == "category":
            m.add_command(label="Новая подкатегория",
                          command=lambda: self._new_category(a))
            m.add_command(label="Новый набор…",
                          command=lambda: self._new_set(a))
            m.add_separator()
            m.add_command(label="Переименовать",
                          command=lambda: self._rename_category(a))
            m.add_command(label="Удалить (рекурсивно)",
                          command=lambda: self._delete_category(a))
        elif kind == "set":
            m.add_command(label="Добавить элемент…",
                          command=lambda: self._add_element_to_set(a))
            m.add_command(label="Переименовать набор",
                          command=lambda: self._rename_set(a))
            m.add_command(label="Удалить набор",
                          command=lambda: self._delete_set(a))
        elif kind == "element":
            stype = self.db.sets[a]["type"]
            if stype == S.T_CARD:
                m.add_command(label="Открыть карту",
                              command=lambda: self.on_card_open(a, b))
            m.add_command(label="Редактировать элемент…",
                          command=lambda: self._edit_element(a, b))
            m.add_command(label="Удалить элемент",
                          command=lambda: self._delete_element(a, b))
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    def _new_category(self, parent):
        t = ask_title(self, "Новая категория")
        if t:
            try:
                self.db.create_category(t, parent)
            except StorageError as e:
                messagebox.showerror("Ошибка", str(e))
            self.refresh()

    def _new_set(self, cid):
        dlg = SetDialog(self, self.db, cid)
        self.wait_window(dlg)
        self.refresh()

    def _rename_category(self, cid):
        t = ask_title(self, "Переименовать категорию",
                      self.db.categories[cid]["title"])
        if t:
            try:
                self.db.rename_category(cid, t)
            except StorageError as e:
                messagebox.showerror("Ошибка", str(e))
            self.refresh()

    def _delete_category(self, cid):
        title = self.db.categories[cid]["title"]
        if messagebox.askyesno("Удаление",
                               f"Удалить категорию «{title}» со всем содержимым?"):
            try:
                self.db.delete_category(cid, recursive=True)
            except StorageError as e:
                messagebox.showerror("Ошибка", str(e))
            self.refresh()

    def _rename_set(self, sid):
        t = ask_title(self, "Переименовать набор", self.db.sets[sid]["title"])
        if t:
            try:
                self.db.rename_set(sid, t)
            except StorageError as e:
                messagebox.showerror("Ошибка", str(e))
            self.refresh()

    def _delete_set(self, sid):
        if messagebox.askyesno("Удаление",
                               f"Удалить набор «{self.db.sets[sid]['title']}»?"):
            self.db.delete_set(sid)
            self.refresh()

    def _add_element_to_set(self, sid):
        etype = self.db.sets[sid]["type"]
        res = new_element_dialog(self, self.db, etype)
        if res:
            self.refresh()
            if etype == S.T_CARD:
                self.on_card_open(sid, res[1])

    def _edit_element(self, sid, slug):
        etype = self.db.sets[sid]["type"]
        if etype == S.T_CARD:
            self.on_card_open(sid, slug)
            return
        dlg = ElementEditDialog(self, self.db, sid, slug)
        self.wait_window(dlg)
        self.refresh()

    def _delete_element(self, sid, slug):
        used = self.db.usage_count(slug, self.db.sets[sid]["type"])
        if used and not messagebox.askyesno(
                "Используется",
                f"Элемент используется в {used} карте(ах).\nУдалить всё равно?"):
            return
        self.db.remove_element(sid, slug)
        self.refresh()


class SetDialog(tk.Toplevel):
    """Создание набора: название + тип элементов (инвариант один-тип-файл)."""

    def __init__(self, master, db, cid):
        super().__init__(master)
        self.db, self.cid = db, cid
        self.title("Новый набор")
        self.geometry("340x200")
        self.transient(master); self.grab_set()
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Категория: {' / '.join(db.category_path_titles(cid))}")\
            .pack(anchor="w")
        ttk.Label(frm, text="Название:").pack(anchor="w", pady=(6, 0))
        self.name = tk.StringVar(); ttk.Entry(frm, textvariable=self.name)\
            .pack(fill="x")
        ttk.Label(frm, text="Тип элементов (один тип на набор):")\
            .pack(anchor="w", pady=(6, 0))
        types = list(S.ELEMENT_TYPES)
        self.type = tk.StringVar(value=S.T_CARD)
        cb = ttk.Combobox(frm, state="readonly",
                          values=[f"{S.TYPE_LABELS[t]} ({t})" for t in types])
        cb.current(types.index(S.T_CARD)); cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>",
                lambda e: setattr(self.type, "_ix", types.index(cb.current())))
        bf = ttk.Frame(frm); bf.pack(fill="x", pady=8)

        def ok():
            t = types[cb.current()]
            n = self.name.get().strip()
            if n:
                try:
                    db.create_set(n, cid, t)
                except StorageError as ex:
                    messagebox.showerror("Ошибка", str(ex)); return
                self.destroy()
        ttk.Button(bf, text="Создать", command=ok).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)


class ElementEditDialog(tk.Toplevel):
    """JSON-редактор произвольного не-карточного элемента."""

    def __init__(self, master, db, sid, slug):
        super().__init__(master)
        self.db, self.sid, self.slug = db, sid, slug
        item = db.get_elements(sid)[slug]
        self.title(f"Элемент: {item.get('name', slug)}")
        self.geometry("520x420")
        self.transient(master); self.grab_set()
        frm = ttk.Frame(self, padding=6); frm.pack(fill="both", expand=True)
        self.txt = tk.Text(frm, wrap="none")
        self.txt.insert("1.0", __import__("json").dumps(item, ensure_ascii=False, indent=2))
        self.txt.pack(fill="both", expand=True)
        bf = ttk.Frame(frm); bf.pack(fill="x", pady=6)

        def save():
            try:
                obj = __import__("json").loads(self.txt.get("1.0", "end"))
            except Exception as e:
                messagebox.showerror("JSON", f"Некорректный JSON: {e}"); return
            obj.pop("slug", None)
            db.update_element(sid, slug, obj)
            self.destroy()
        ttk.Button(bf, text="Сохранить", command=save).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)
