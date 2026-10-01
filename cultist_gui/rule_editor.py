# -*- coding: utf-8 -*-
"""Редактор правил трансмутации карты (подсловарь card['transmutations']).

Каждое правило — набор полей RULE_FIELDS; поля inputs/result/additional/...
принимают ссылки на карты и атрибуты через Drag&Drop из дерева/библиотеки
или кнопку «+».  Правила могут быть сохранены как переиспользуемый элемент
типа «rule» (кнопка «Сохранить в библиотеку правил»).
"""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List

from cultist_db import schema as S
from .widgets import parse_payload, pick_element, register_drop


class RuleEditorDialog(tk.Toplevel):
    def __init__(self, master, db, card: Dict[str, Any]):
        super().__init__(master)
        self.db = db
        self.card = card
        self.rules: Dict[str, Dict[str, Any]] = copy.deepcopy(
            card.get("transmutations") or {})
        self.current: str = ""
        self.title("Правила трансмутации")
        self.geometry("720x540")
        self.transient(master); self.grab_set()

        outer = ttk.Frame(self, padding=6); outer.pack(fill="both", expand=True)
        pw = ttk.Panedwindow(outer, orient="horizontal")
        pw.pack(fill="both", expand=True)

        # ---- список правил слева -------------------------------------
        lf = ttk.LabelFrame(pw, text="Правила"); pw.add(lf, weight=1)
        self.lst = tk.Listbox(lf, exportselection=False)
        self.lst.pack(fill="both", expand=True, padx=4, pady=4)
        self.lst.bind("<<ListboxSelect>>", lambda e: self._load_current())
        bf = ttk.Frame(lf); bf.pack(fill="x", padx=4, pady=2)
        ttk.Button(bf, text="+", command=self._add).pack(side="left")
        ttk.Button(bf, text="−", command=self._del).pack(side="left", padx=2)
        ttk.Button(bf, text="Копия", command=self._dup).pack(side="left", padx=2)

        # ---- редактор справа -------------------------------------------
        rf = ttk.LabelFrame(pw, text="Поля правила"); pw.add(rf, weight=3)
        grid = ttk.Frame(rf); grid.pack(fill="both", expand=True, padx=6, pady=6)
        self.fields: Dict[str, tk.Text] = {}
        for i, (key, label) in enumerate(S.RULE_FIELDS):
            ttk.Label(grid, text=label + ":").grid(row=i, column=0,
                                                   sticky="nw", padx=4, pady=3)
            t = tk.Text(grid, height=2, width=52)
            t.grid(row=i, column=1, sticky="we", padx=4)
            register_drop(t, lambda data, tt=t: self._drop_field(tt, data))
            bfr = ttk.Frame(grid); bfr.grid(row=i, column=2, sticky="ns")
            ttk.Button(bfr, text="+карта", width=8,
                       command=lambda k=key: self._pick_card_into(k)).pack()
            ttk.Button(bfr, text="+аспект", width=8,
                       command=lambda k=key: self._pick_aspect_into(k)).pack()
            self.fields[key] = t
        grid.columnconfigure(1, weight=1)

        bottom = ttk.Frame(outer); bottom.pack(fill="x", pady=6)
        ttk.Button(bottom, text="Сохранить в библиотеку правил",
                   command=self._export_rule).pack(side="left")
        ttk.Button(bottom, text="Применить к карте", command=self._apply_ok)\
            .pack(side="right")
        ttk.Button(bottom, text="Отмена", command=self.destroy)\
            .pack(side="right", padx=4)
        self._refresh_list()

    # -------------------------------------------------------------- list ops
    def _refresh_list(self, sel_name: str = ""):
        self.lst.delete(0, "end")
        for name in sorted(self.rules):
            self.lst.insert("end", name)
            if name == sel_name:
                self.lst.selection_set(self.lst.size() - 1)

    def _selected_name(self) -> str:
        s = self.lst.curselection()
        return self.lst.get(s[0]) if s else ""

    def _store_current(self):
        if self.current and self.current in self.rules:
            r = self.rules[self.current]
            for k, t in self.fields.items():
                r[k] = t.get("1.0", "end").strip()

    def _load_current(self):
        self._store_current()
        name = self._selected_name()
        self.current = name
        r = self.rules.get(name, {})
        for k, t in self.fields.items():
            t.delete("1.0", "end")
            v = r.get(k, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            t.insert("1.0", v)

    def _add(self):
        from .widgets import ask_title
        name = ask_title(self, "Имя правила", f"rule-{len(self.rules)+1}")
        if name and name not in self.rules:
            self.rules[name] = {k: "" for k, _ in S.RULE_FIELDS}
            self._refresh_list(name); self._load_current()

    def _del(self):
        name = self._selected_name()
        if name:
            self.rules.pop(name, None)
            self.current = ""
            self._refresh_list(); self._load_current()

    def _dup(self):
        name = self._selected_name()
        if name:
            i = 2
            while f"{name}-copy{i}" in self.rules:
                i += 1
            self.rules[f"{name}-copy{i}"] = copy.deepcopy(self.rules[name])
            self._refresh_list(f"{name}-copy{i}"); self._load_current()

    # -------------------------------------------------------------- helpers
    def _append_to_field(self, key: str, text: str):
        t = self.fields[key]
        cur = t.get("1.0", "end").rstrip()
        t.delete("1.0", "end")
        t.insert("1.0", (cur + ", " + text).strip(", "))

    def _pick_card_into(self, key):
        res = pick_element(self, self.db, S.T_CARD, multi=True)
        for r in res:
            self._append_to_field(key, r["item"].get("name", r["slug"]))

    def _pick_aspect_into(self, key):
        res = pick_element(self, self.db, S.T_ASPECT, multi=True)
        for r in res:
            self._append_to_field(key, r["item"].get("name", r["slug"]))

    def _drop_field(self, t: tk.Text, data: str):
        p = parse_payload(data)
        if not p:
            return
        name = p.get("name") or p.get("slug") or ""
        if p.get("kind") in ("element", "cardref") and name:
            cur = t.get("1.0", "end").rstrip()
            t.delete("1.0", "end")
            t.insert("1.0", (cur + ", " + name).strip(", "))

    # -------------------------------------------------------------- save
    def _apply_ok(self):
        self._store_current()
        self.card["transmutations"] = self.rules
        self.destroy()

    def _export_rule(self):
        self._store_current()
        if not self.current:
            messagebox.showinfo("Правило", "Сначала выберите правило.")
            return
        item = S.default_element(S.T_RULE)
        item["name"] = self.current
        item.update({k: v for k, v in self.rules[self.current].items()})
        sids = self.db.all_sets_of_type(S.T_RULE)
        if sids:
            sid = sids[0]
        else:
            cats = [c["id"] for c in self.db.categories.values()]
            if not cats:
                messagebox.showerror("Ошибка", "Нет категорий для набора правил")
                return
            sid = self.db.create_set("Правила", cats[0], S.T_RULE)
        self.db.add_element(sid, item)
        messagebox.showinfo("Правило",
                            f"Правило «{self.current}» сохранено в набор "
                            f"«{self.db.sets[sid]['title']}» как переиспользуемый элемент.")
