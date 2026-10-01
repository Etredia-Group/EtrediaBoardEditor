# -*- coding: utf-8 -*-
"""Конструктор карты — визуальный редактор в виде макета карточки.

Слева — «карточка» (превью с drop-зонами цвета/иконки), справа — группы
атрибутов.  Атрибуты добавляются перетаскиванием из библиотеки или двойным
кликом по списку; внутри списков поддерживается reorder и изменение count.
Сохранение выполняет promote новых локальных объектов {"new": {...}} в
переиспользуемые наборы.
"""
from __future__ import annotations

import copy
import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

from cultist_db import schema as S
from cultist_db.storage import Database, StorageError

from .widgets import (DND_ELEMENT, ensure_drag_source, make_payload,
                      parse_payload, pick_element, register_drop)


class DropList(ttk.Frame):
    """Один атрибутный список карты: TreeView + кнопки + DnD приёмник."""

    def __init__(self, master, key: str, spec: dict, db: Database,
                 card_getter, on_change, width=260, height=7):
        super().__init__(master)
        self.key = key
        self.spec = spec
        self.db = db
        self.card_getter = card_getter
        self.on_change = on_change
        self.etype = spec["target"]
        self.store = spec.get("store", "count")

        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Label(head, text=spec["label"],
                  font=("", "9", "bold")).pack(side="left")
        u = "уникальный" if spec["unique"] else f"{self.store} ✔"
        ttk.Label(head, text=f"[{u}]", foreground="gray").pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(body)
        self.tree = ttk.Treeview(body, columns=("name", "cnt"),
                                 show="tree headings", height=height,
                                 yscrollcommand=vsb.set, selectmode="browse")
        vsb.config(command=self.tree.yview)
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=18, stretch=False)
        self.tree.heading("name", text="Элемент")
        self.tree.column("name", width=width - 90, anchor="w")
        self.tree.heading("cnt", text="×")
        self.tree.column("cnt", width=40, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("unresolved", foreground="#b00020")

        self.tree.bind("<Double-1>", self._on_double_edit)
        # reorder drag&drop внутри списка
        try:
            if ensure_drag_source(self.tree):
                self.tree.dnd_bind("<<DragInitCmd>>", self._drag_init)
        except Exception:
            pass
        register_drop(self.tree, self._on_drop)

        btns = ttk.Frame(self)
        btns.pack(fill="x")
        for txt, cmd in (("+", self._add_dialog), ("−", self._remove),
                         ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1)),
                         ("+1", lambda: self._bump(1)), ("-1", lambda: self._bump(-1))):
            ttk.Button(btns, text=txt, width=3, command=cmd).pack(side="left", padx=1)

    # ----------------------------------------------------------- rendering
    def refresh(self):
        lst = self.card_getter().get(self.key, [])
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(lst):
            ref = S.ref_of(item)
            if isinstance(item, dict) and "new" in item:
                name = "★ НОВЫЙ: " + (item["new"].get("name") or "(без имени)")
                cnt = ""
                tags = ("unresolved",)
            else:
                found = self.db.find_element(ref, self.etype)
                name = found[1].get("name", ref) if found else f"?{ref}"
                cnt = "" if self.spec["unique"] else str(S.count_of(item, self.store))
                tags = ()
            self.tree.insert("", "end", iid=str(i), text="•",
                             values=(name, cnt), tags=tags)

    # ------------------------------------------------------------- editing
    def _list(self) -> List[dict]:
        return self.card_getter().setdefault(self.key, [])

    def add_ref(self, slug: str):
        lst = self._list()
        if self.spec["unique"]:
            if any(S.ref_of(x) == slug for x in lst):
                return False
        else:
            for x in lst:
                if S.is_ref(x) and S.ref_of(x) == slug:
                    x[self.store] = S.count_of(x, self.store) + 1
                    self.refresh(); self.on_change(); return True
        lst.append({"ref": slug})
        self.refresh(); self.on_change(); return True

    def _add_dialog(self):
        res = pick_element(self, self.db, self.etype, multi=True)
        for r in res:
            self.add_ref(r["slug"])

    def _remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        del self._list()[i]
        self.refresh(); self.on_change()

    def _move(self, d):
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0]); j = max(0, min(len(self._list()) - 1, i + d))
        if i == j:
            return
        lst = self._list()
        lst[i], lst[j] = lst[j], lst[i]
        self.refresh(); self.tree.selection_set(str(j)); self.on_change()

    def _bump(self, d):
        sel = self.tree.selection()
        if not sel or self.spec["unique"]:
            return
        item = self._list()[int(sel[0])]
        if not isinstance(item, dict):
            return
        item[self.store] = max(1, S.count_of(item, self.store) + d)
        self.refresh(); self.on_change()

    def _on_double_edit(self, ev):
        """Двойной клик: открыть/редактировать элемент-источник."""
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        item = self._list()[int(iid)]
        if isinstance(item, dict) and "new" in item:
            from .tree_panel import ElementEditDialog  # не подходит — local new
            dlg = _NewLocalEditor(self, item["new"], self.db, self.etype)
            self.wait_window(dlg)
            self.refresh(); self.on_change()
            return
        found = self.db.find_element(S.ref_of(item), self.etype)
        if found:
            sid, _it = found
            from .tree_panel import ElementEditDialog
            d = ElementEditDialog(self, self.db, sid, S.ref_of(item))
            self.wait_window(d)
            self.refresh()

    # ---------------------------------------------------------------- DnD
    def _drag_init(self, ev):
        sel = self.tree.selection()
        if not sel:
            return ("NONE", "none", "")
        i = int(sel[0])
        payload = make_payload("cardlist-move", key=self.key, index=i)
        return (DND_ELEMENT, "copy", payload)

    def _on_drop(self, data: str):
        p = parse_payload(data)
        if not p:
            return
        if p.get("kind") == "element" and p.get("etype") == self.etype:
            self.add_ref(p["slug"])
        elif p.get("kind") == "cardlist-move" and p.get("key") == self.key:
            src = int(p["index"])
            lst = self._list()
            if 0 <= src < len(lst):
                item = lst.pop(src)
                nsel = self.tree.selection()
                pos = int(nsel[0]) if nsel else len(lst)
                lst.insert(min(pos, len(lst)), item)
                self.refresh(); self.on_change()


class _NewLocalEditor(tk.Toplevel):
    """Редактор локального нового объекта {'new': {...}} перед promote."""

    def __init__(self, master, obj: dict, db, etype):
        super().__init__(master)
        self.obj, self.etype = obj, etype
        self.title("Новый локальный атрибут (будет поднят в базу при сохранении)")
        self.geometry("420x260")
        self.transient(master); self.grab_set()
        f = ttk.Frame(self, padding=8); f.pack(fill="both", expand=True)
        ttk.Label(f, text="Название:").pack(anchor="w")
        self.name = tk.StringVar(value=obj.get("name", ""))
        ttk.Entry(f, textvariable=self.name).pack(fill="x")
        ttk.Label(f, text="JSON:").pack(anchor="w", pady=(6, 0))
        self.txt = tk.Text(f, height=8)
        self.txt.insert("1.0", json.dumps(obj, ensure_ascii=False, indent=2))
        self.txt.pack(fill="both", expand=True)
        bf = ttk.Frame(f); bf.pack(fill="x", pady=6)

        def save():
            try:
                new_obj = json.loads(self.txt.get("1.0", "end"))
            except Exception as e:
                messagebox.showerror("JSON", str(e)); return
            new_obj["name"] = self.name.get().strip() or new_obj.get("name", "")
            obj.clear(); obj.update(new_obj)
            self.destroy()
        ttk.Button(bf, text="OK", command=save).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)


# ---------------------------------------------------------------------------
# Конструктор карты
# ---------------------------------------------------------------------------

GROUP_SCALARS_1 = ["name", "border", "reverse"]
GROUP_SCALARS_2 = ["description", "flavor"]
LIST_ORDER = ["aspects", "elements", "influences", "resources", "properties",
              "suppressions", "hours", "emotions", "tags", "rules"]
LINK_ORDER = list(S.CARD_LINKS.keys())


class CardEditor(ttk.Frame):
    """Вкладка конструктора одной карты."""

    def __init__(self, master, app, sid: str, slug: str):
        super().__init__(master)
        self.app = app
        self.db: Database = app.db
        self.sid = sid
        self.slug = slug
        self.dirty = False
        card = copy.deepcopy(self.db.get_elements(sid).get(slug, S.default_card()))
        card["slug"] = slug
        self.card: Dict[str, Any] = card

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # ---------------- левая колонка: превью-карточка ----------------
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        self.canvas = tk.Canvas(left, width=250, height=360, bg="#1a1a22",
                                highlightthickness=0)
        self.canvas.pack(pady=10)
        register_drop(self.canvas, self._on_drop_card)
        self.canvas.bind("<Double-1>", self._edit_transmutations)

        meta = ttk.Frame(left); meta.pack(fill="x", padx=8)
        ttk.Button(meta, text="Правила трансмутации…",
                   command=self._edit_transmutations).pack(side="left")
        ttk.Button(meta, text="Сохранить (Ctrl+S)",
                   command=self.save).pack(side="right")
        self.lbl_state = ttk.Label(left, text="", foreground="gray")
        self.lbl_state.pack(anchor="w", padx=8)

        # ---------------- правая колонка: атрибуты ----------------------
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        tab1 = ttk.Frame(nb); nb.add(tab1, text="Основные")
        inner = ttk.Frame(tab1, padding=8); inner.pack(fill="both", expand=True)
        self.scalar_vars: Dict[str, Any] = {}
        g = ttk.LabelFrame(inner, text="Скалярные атрибуты"); g.pack(fill="x")
        for i, k in enumerate(GROUP_SCALARS_1):
            self._make_scalar(g, k, row=i)
        self.txt_desc = self._make_text(g, "description", len(GROUP_SCALARS_1))
        self.txt_flavor = self._make_text(g, "flavor", len(GROUP_SCALARS_1) + 1)

        g2 = ttk.LabelFrame(inner, text="Цвет / иконка (drop на карточку слева)")
        g2.pack(fill="x", pady=6)
        self.var_color = tk.StringVar(value=card.get("color", ""))
        self.var_icon = tk.StringVar(value=card.get("icon", ""))
        ttk.Label(g2, text="Цвет:").grid(row=0, column=0, sticky="w")
        ce = ttk.Entry(g2, textvariable=self.var_color, width=24)
        ce.grid(row=0, column=1, sticky="we")
        ce.bind("<KeyRelease>", lambda e: self._mark_dirty())
        ttk.Button(g2, text="…", width=3,
                   command=lambda: self._pick_ref("color", S.T_COLOR,
                                                  self.var_color)).grid(row=0, column=2)
        ttk.Label(g2, text="Иконка:").grid(row=1, column=0, sticky="w")
        ie = ttk.Entry(g2, textvariable=self.var_icon, width=24)
        ie.grid(row=1, column=1, sticky="we")
        ie.bind("<KeyRelease>", lambda e: self._mark_dirty())
        ttk.Button(g2, text="…", width=3,
                   command=lambda: self._pick_ref("icon", S.T_ICON,
                                                  self.var_icon)).grid(row=1, column=2)
        g2.columnconfigure(1, weight=1)

        tab2 = ttk.Frame(nb); nb.add(tab2, text="Атрибуты")
        cols = ttk.Frame(tab2); cols.pack(fill="both", expand=True)
        self.droplists: Dict[str, DropList] = {}
        for ci in range(2):
            cframe = ttk.Frame(cols); cframe.pack(side="left", fill="both",
                                                  expand=True, padx=4, pady=4)
            keys = LIST_ORDER[ci::2]
            for k in keys:
                dl = DropList(cframe, k, S.CARD_LISTS[k], self.db,
                              lambda: self.card, self._mark_dirty, height=4)
                dl.pack(fill="both", expand=True, pady=2)
                self.droplists[k] = dl

        tab3 = ttk.Frame(nb); nb.add(tab3, text="Связи")
        lframe = ttk.Frame(tab3, padding=8); lframe.pack(fill="both", expand=True)
        self.link_lists: Dict[str, ttk.Treeview] = {}
        for k in LINK_ORDER:
            lf = ttk.LabelFrame(lframe, text=S.CARD_LINKS[k]["label"])
            lf.pack(fill="both", expand=True, pady=3)
            t = ttk.Treeview(lf, columns=("name",), show="headings", height=3)
            t.heading("name", text="Карта")
            t.pack(side="left", fill="both", expand=True)
            bts = ttk.Frame(lf); bts.pack(side="right")
            ttk.Button(bts, text="+", width=3,
                       command=lambda kk=k: self._link_add(kk)).pack()
            ttk.Button(bts, text="−", width=3,
                       command=lambda kk=k: self._link_del(kk)).pack()
            register_drop(t, lambda data, kk=k: self._link_drop(kk, data))
            self.link_lists[k] = t

        self._load_scalars()
        self.refresh_all()

    # ------------------------------------------------------- scalars
    def _make_scalar(self, parent, key, row):
        spec = S.CARD_SCALARS[key]
        ttk.Label(parent, text=spec["label"] + ":").grid(
            row=row, column=0, sticky="w", padx=4, pady=2)
        if spec["kind"] == "enum":
            v = tk.StringVar()
            cb = ttk.Combobox(parent, textvariable=v, state="readonly",
                              values=list(spec["values"]))
            cb.bind("<<ComboboxSelected>>", lambda e: self._mark_dirty())
        elif spec["kind"] == "bool":
            v = tk.IntVar()
            cb = ttk.Checkbutton(parent, variable=v,
                                 command=self._mark_dirty)
        elif spec["kind"] == "int":
            v = tk.IntVar()
            lo, hi = spec.get("range", (0, 13))
            cb = ttk.Spinbox(parent, from_=lo, to=hi, textvariable=v, width=6,
                             command=self._mark_dirty)
        else:  # str (например «Название»)
            v = tk.StringVar()
            cb = ttk.Entry(parent, textvariable=v, width=32)
            cb.bind("<KeyRelease>", lambda e: self._mark_dirty())
        cb.grid(row=row, column=1, sticky="w", padx=4)
        self.scalar_vars[key] = v

    def _make_text(self, parent, key, row):
        spec = S.CARD_SCALARS[key]
        ttk.Label(parent, text=spec["label"] + ":").grid(
            row=row, column=0, sticky="nw", padx=4, pady=2)
        t = tk.Text(parent, height=3, width=44)
        t.grid(row=row, column=1, sticky="we", padx=4)
        t.bind("<<Modified>>", self._text_modified)
        parent.columnconfigure(1, weight=1)
        return t

    def _text_modified(self, ev):
        w = ev.widget
        if w.edit_modified():
            self._mark_dirty()
            w.edit_modified(False)

    def _load_scalars(self):
        c = self.card
        for k, v in self.scalar_vars.items():
            val = c.get(k, "")
            if S.CARD_SCALARS[k]["kind"] == "bool":
                v.set(1 if val else 0)
            elif S.CARD_SCALARS[k]["kind"] == "int":
                v.set(int(val or 0))
            else:
                v.set(val or "")
        self.txt_desc.delete("1.0", "end"); self.txt_desc.insert("1.0", c.get("description", ""))
        self.txt_flavor.delete("1.0", "end"); self.txt_flavor.insert("1.0", c.get("flavor", ""))

    def _collect_scalars(self):
        c = self.card
        for k, v in self.scalar_vars.items():
            kind = S.CARD_SCALARS[k]["kind"]
            if kind == "int":
                try:
                    c[k] = int(v.get())
                except Exception:
                    c[k] = 0
            elif kind == "bool":
                c[k] = bool(v.get())
            else:
                c[k] = v.get()
        c["description"] = self.txt_desc.get("1.0", "end").strip()
        c["flavor"] = self.txt_flavor.get("1.0", "end").strip()
        c["color"] = self.var_color.get().strip()
        c["icon"] = self.var_icon.get().strip()

    # ------------------------------------------------------- refs color/icon
    def _pick_ref(self, field, etype, var):
        res = pick_element(self, self.db, etype)
        if res:
            var.set(res[0]["slug"]); self._mark_dirty()

    # ------------------------------------------------------- links
    def _link_add(self, key):
        res = pick_element(self, self.db, S.T_CARD, multi=True)
        for r in res:
            lst = self.card.setdefault(key, [])
            if r["slug"] not in [S.ref_of(x) for x in lst]:
                lst.append({"ref": r["slug"]})
        self.refresh_links(); self._mark_dirty()

    def _link_del(self, key):
        t = self.link_lists[key]
        sel = t.selection()
        if sel:
            i = t.index(sel[0])
            del self.card[key][i]
            self.refresh_links(); self._mark_dirty()

    def _link_drop(self, key, data):
        p = parse_payload(data)
        if p and p.get("kind") == "cardref":
            lst = self.card.setdefault(key, [])
            if p["slug"] not in [S.ref_of(x) for x in lst]:
                lst.append({"ref": p["slug"]})
                self.refresh_links(); self._mark_dirty()

    def refresh_links(self):
        for k, t in self.link_lists.items():
            t.delete(*t.get_children())
            for item in self.card.get(k, []):
                ref = S.ref_of(item)
                found = self.db.find_element(ref, S.T_CARD)
                name = found[1].get("name", ref) if found else f"?{ref}"
                t.insert("", "end", values=(name,))

    # ------------------------------------------------------- preview canvas
    def refresh_all(self):
        for dl in self.droplists.values():
            dl.refresh()
        self.refresh_links()
        self.draw_preview()

    def draw_preview(self):
        cv = self.canvas
        cv.delete("all")
        W, H = 250, 360
        color_hex = "#c8a24b"
        cslug = self.card.get("color", "")
        if cslug:
            found = self.db.find_element(cslug, S.T_COLOR)
            if found:
                color_hex = found[1].get("hex", color_hex)
        border = int(self.card.get("border", 0) or 0)
        cv.create_rectangle(6, 6, W - 6, H - 6, fill="#26262e",
                            outline=color_hex, width=2 + border * 2)
        glyph = "?"
        islug = self.card.get("icon", "")
        if islug:
            found = self.db.find_element(islug, S.T_ICON)
            if found:
                glyph = found[1].get("glyph", "?")
        cv.create_text(W // 2, 70, text=glyph, fill=color_hex,
                       font=("", 42))
        name = self.card.get("name") or "(без названия)"
        cv.create_text(W // 2, 130, text=name, fill="#e8e0cf",
                       font=("", 13, "bold"), width=W - 40)
        aspects = []
        for it in self.card.get("aspects", []):
            f = self.db.find_element(S.ref_of(it), S.T_ASPECT)
            aspects.append(f[1].get("name", "?") if f else S.ref_of(it))
        cv.create_text(W // 2, 185, text=", ".join(aspects[:4]),
                       fill="#b7aebb", font=("", 8), width=W - 30)
        desc = (self.card.get("description") or "")[:160]
        cv.create_text(W // 2, 250, text=desc, fill="#cfc8b8", font=("", 8),
                       width=W - 40, justify="center")
        bdr = int(self.card.get("border", 0) or 0)
        cv.create_text(24, H - 24, text=f"border {bdr}", fill="#8a8578",
                       font=("", 9))
        if self.card.get("reverse"):
            cv.create_text(W - 24, H - 24, text="↺ reverse", fill="#8a8578",
                           font=("", 9))
        cv.create_text(W // 2, H - 24, text="drop: цвет/иконка ↜",
                       fill="#555", font=("", 7))

    def _on_drop_card(self, data):
        p = parse_payload(data)
        if not p or p.get("kind") != "element":
            return
        if p.get("etype") == S.T_COLOR:
            self.var_color.set(p["slug"])
        elif p.get("etype") == S.T_ICON:
            self.var_icon.set(p["slug"])
        else:
            key = {S.T_ASPECT: "aspects", S.T_TAG: "tags",
                   S.T_INFLUENCE: "influences", S.T_ELEMENT: "elements",
                   S.T_RESOURCE: "resources", S.T_PROPERTY: "properties",
                   S.T_SUPPRESSION: "suppressions", S.T_HOURS: "hours",
                   S.T_EMOTION: "emotions", S.T_RULE: "rules"}.get(p["etype"])
            if key:
                self.droplists[key].add_ref(p["slug"])
                return
        self._mark_dirty()

    # ------------------------------------------------------- transmutations
    def _edit_transmutations(self):
        from .rule_editor import RuleEditorDialog
        d = RuleEditorDialog(self, self.db, self.card)
        self.wait_window(d)
        self._mark_dirty()

    # ------------------------------------------------------- dirty/save
    def _mark_dirty(self, *_a):
        self._collect_scalars()
        self.dirty = True
        self.lbl_state.config(text="● изменено — нажмите «Сохранить»",
                              foreground="#b06000")
        self.draw_preview()

    def save(self, *_a) -> bool:
        """Сохраняет карту в базу. True при успехе (используется app._on_close)."""
        self._collect_scalars()
        warns = S.validate_card(self.card, self.db.known_slugs())
        # promote локальных new-объектов в переиспользуемые наборы
        targets = {}
        for etype in {spec["target"] for spec in S.CARD_LISTS.values()}:
            sids = self.db.all_sets_of_type(etype)
            if sids:
                targets[etype] = sids[0]
        try:
            card = self.db.promote_new_items(self.card, targets)
        except StorageError as e:
            messagebox.showerror("Ошибка сохранения", str(e)); return False
        self.card = card
        try:
            self.db.update_element(self.sid, self.slug, card)
        except StorageError as e:
            messagebox.showerror("Ошибка сохранения", str(e)); return False
        self.dirty = False
        self.lbl_state.config(text="сохранено ✓", foreground="#2a7d2a")
        self.app.tree_panel.refresh()
        self.app.library_panel.refresh()
        self.refresh_all()
        if warns:
            unresolved = [w for w in warns if "отсутствует" in w]
            if unresolved:
                messagebox.showwarning("Внимание", "\n".join(unresolved[:8]))
        return True
