# -*- coding: utf-8 -*-
"""Главное окно приложения: дерево слева, редакторы карт в центральном
Notebook, библиотека атрибутов справа.  Ctrl+S сохраняет активную карту."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from cultist_db import schema as S
from cultist_db.seed import seed as seed_db
from cultist_db.storage import Database, StorageError

from .card_editor import CardEditor
from .library_panel import LibraryPanel
from .tree_panel import TreePanel
from .widgets import ask_title, dnd_available

try:
    from tkinterdnd2 import TkinterDnD

    _Base = TkinterDnD.Tk
except Exception:      # pragma: no cover
    _Base = tk.Tk


def create_root_window():
    """Возвращает корневой Tk (с DnD-поддержкой, если доступна)."""
    try:
        return _Base()
    except Exception:  # pragma: no cover
        return tk.Tk()


class App(ttk.Frame):
    def __init__(self, master, db: Database):
        super().__init__(master)
        self.master = master
        self.db = db
        master.title("Cultist Card Manager — редактор игровых карт")
        master.geometry("1360x760")

        self._make_menu()

        pw = ttk.Panedwindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)

        self.tree_panel = TreePanel(pw, db, on_card_open=self.open_card)
        pw.add(self.tree_panel, weight=2)

        center = ttk.Frame(pw); pw.add(center, weight=5)
        self.nb = ttk.Notebook(center)
        self.nb.pack(fill="both", expand=True)
        self.editors: dict = {}   # (sid, slug) -> CardEditor
        self._show_placeholder()

        self.library_panel = LibraryPanel(pw, db,
                                          on_changed=self.tree_panel.refresh)
        pw.add(self.library_panel, weight=2)

        status = "DnD: включён (Tk DND)" if dnd_available() else \
            "DnD недоступен — используйте кнопки +/− и диалоги выбора"
        self.status = ttk.Label(self, text=f"База: {db.root}   |   {status}",
                                relief="sunken", anchor="w")
        self.status.pack(fill="x")
        self.pack(fill="both", expand=True)

        master.bind_all("<Control-s>", self._ctrl_s)
        master.protocol("WM_DELETE_WINDOW", self._on_close)
        self.tree_panel.refresh()

    # ------------------------------------------------------------- menu
    def _make_menu(self):
        m = tk.Menu(self.master)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Новая карта…", command=self._new_card)
        fm.add_separator()
        fm.add_command(label="Сохранить всё", command=self._save_all)
        fm.add_command(label="Экспорт карты в JSON…", command=self._export_card)
        fm.add_command(label="Импорт карты из JSON…", command=self._import_card)
        fm.add_separator()
        fm.add_command(label="Закрыть вкладку", command=self._close_tab)
        m.add_cascade(label="Файл", menu=fm)

        ed = tk.Menu(m, tearoff=0)
        ed.add_command(label="Новая категория…",
                       command=lambda: self.tree_panel._new_category(""))
        ed.add_command(label="Новый набор…", command=self._new_set_here)
        m.add_cascade(label="База", menu=ed)

        hl = tk.Menu(m, tearoff=0)
        hl.add_command(label="О программе", command=self._about)
        m.add_cascade(label="Справка", menu=hl)
        self.master.config(menu=m)

    # ------------------------------------------------------------- tabs
    def _show_placeholder(self):
        ph = ttk.Frame(self.nb)
        ttk.Label(ph, text="Двойной клик по карте в дереве слева — открыть,\n"
                           "или Файл → Новая карта.\n\n"
                           "Перетаскивайте атрибуты из библиотеки справа\n"
                           "на списки атрибутов и на превью карточки.",
                  justify="center", foreground="gray").pack(expand=True)
        self.nb.add(ph, text="Стартовая")
        self._placeholder = ph

    def open_card(self, sid: str, slug: str):
        key = (sid, slug)
        if key in self.editors:
            self.nb.select(self.editors[key]); return
        ed = CardEditor(self.nb, self, sid, slug)
        name = self.db.get_elements(sid).get(slug, {}).get("name", slug)
        self.nb.add(ed, text=name[:24])
        self.editors[key] = ed
        if getattr(self, "_placeholder", None) and \
                self.nb.tabs().index(str(ed)) is not None:
            pass
        try:
            self.nb.forget(self._placeholder)
        except Exception:
            pass
        self.nb.select(ed)

    def current_editor(self):
        w = None
        try:
            sel = self.nb.select()
            w = self.nb.nametowidget(sel)
        except Exception:
            pass
        return w if isinstance(w, CardEditor) else None

    def _ctrl_s(self, _ev):
        ed = self.current_editor()
        if ed:
            ed.save()

    def _close_tab(self):
        ed = self.current_editor()
        if ed:
            if ed.dirty and not messagebox.askyesno(
                    "Закрыть", "Есть несохранённые изменения. Закрыть?"):
                return
            self.editors.pop((ed.sid, ed.slug), None)
            self.nb.forget(ed)

    # ------------------------------------------------------------- actions
    def _new_card(self):
        # выбрать набор карт
        card_sets = [st for st in self.db.sets.values()
                     if st["type"] == S.T_CARD]
        if not card_sets:
            messagebox.showerror("Нет наборов",
                                 "Сначала создайте набор типа «Карты» "
                                 "(правый клик по категории в дереве).")
            return
        names = [" / ".join(self.db.category_path_titles(st["category"]))
                 + " ▸ " + st["title"] for st in card_sets]
        dlg = _PickDialog(self, "Новая карта: выберите набор", names)
        self.wait_window(dlg)
        if dlg.choice is None:
            return
        st = card_sets[dlg.choice]
        title = ask_title(self, "Название карты", "Новая карта")
        if not title:
            return
        item = S.default_card()
        item["name"] = title
        slug = self.db.add_element(st["id"], item)
        self.tree_panel.refresh()
        self.open_card(st["id"], slug)

    def _new_set_here(self):
        kind, a, _b = self.tree_panel.selected()
        cid = a if kind == "category" else ""
        if not self.db.categories:
            messagebox.showerror("Пусто", "Сначала создайте категорию.")
            return
        from .tree_panel import SetDialog
        d = SetDialog(self, self.db, cid or next(iter(self.db.categories)))
        self.wait_window(d)
        self.tree_panel.refresh()

    def _save_all(self):
        ed = self.current_editor()
        if ed and ed.dirty:
            ed.save()
        self.db.save()
        messagebox.showinfo("Сохранено", "База сохранена на диск.")

    def _export_card(self):
        ed = self.current_editor()
        if not ed:
            messagebox.showinfo("Экспорт", "Откройте карту в редакторе.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                         filetypes=[("JSON", "*.json")])
        if p:
            import json
            with open(p, "w", encoding="utf-8") as f:
                json.dump(ed.card, f, ensure_ascii=False, indent=2)

    def _import_card(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        import json
        try:
            with open(p, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as e:
            messagebox.showerror("Импорт", str(e)); return
        if not isinstance(obj, dict) or obj.get("type") != S.T_CARD:
            messagebox.showerror("Импорт", "Это не JSON-карта."); return
        card_sets = [st for st in self.db.sets.values()
                     if st["type"] == S.T_CARD]
        if not card_sets:
            messagebox.showerror("Импорт", "Нет набора карт."); return
        names = [st["title"] for st in card_sets]
        dlg = _PickDialog(self, "Импорт: в какой набор?", names)
        self.wait_window(dlg)
        if dlg.choice is None:
            return
        st = card_sets[dlg.choice]
        obj.pop("slug", None)
        slug = self.db.add_element(st["id"], obj)
        self.tree_panel.refresh()
        self.open_card(st["id"], slug)

    def _about(self):
        messagebox.showinfo(
            "О программе",
            "Менеджер-редактор игровых карт в стиле Cultist Simulator.\n"
            "Хранение: JSON, древовидные категории, наборы (1 файл = 1 тип).\n"
            "Переиспользуемые атрибуты хранятся отдельно и подключаются по ссылкам.")

    def _on_close(self):
        dirty = [e for e in self.editors.values() if e.dirty]
        if dirty:
            ans = messagebox.askyesnocancel(
                "Выход",
                f"Есть несохранённые вкладки ({len(dirty)}).\n"
                "Сохранить и выйти?")
            if ans is None:          # Отмена — остаёмся в программе
                return
            if ans:                  # Да — сохранить всеdirty-вкладки
                failed = []
                for e in dirty:
                    try:
                        if not e.save():
                            failed.append(e)
                    except Exception as ex:
                        failed.append(e)
                        print("save error:", ex)
                if failed:
                    messagebox.showerror(
                        "Выход отменён",
                        f"Не удалось сохранить вкладок: {len(failed)}.\n"
                        "Проверьте предупреждения и повторите.")
                    return
            # Нет — выходим без сохранения
        try:
            self.db.save()
        except Exception as e:
            messagebox.showerror("Ошибка записи базы", str(e))
            return
        self.master.destroy()


class _PickDialog(tk.Toplevel):
    def __init__(self, master, title: str, values):
        super().__init__(master)
        self.choice = None
        self.title(title); self.geometry("420x320")
        self.transient(master); self.grab_set()
        f = ttk.Frame(self, padding=8); f.pack(fill="both", expand=True)
        self.lb = tk.Listbox(f, exportselection=False)
        for v in values:
            self.lb.insert("end", v)
        self.lb.pack(fill="both", expand=True)
        bf = ttk.Frame(f); bf.pack(fill="x", pady=6)

        def ok():
            s = self.lb.curselection()
            if s:
                self.choice = s[0]; self.destroy()
        ttk.Button(bf, text="Выбрать", command=ok).pack(side="right")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right", padx=4)
        self.lb.bind("<Double-1>", lambda e: ok())
