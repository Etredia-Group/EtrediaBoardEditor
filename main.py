# -*- coding: utf-8 -*-
"""Cultist Card Manager — интерактивный менеджер-редактор игровых карт.

Запуск:
    python main.py [путь_к_базе]        (по умолчанию ./data)

Флаги:
    --seed         заполнить пустую базу демонстрационными данными
    --no-seed      не предлагать заполнение, создать пустую базу
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Редактор карт в стиле "
                                             "Cultist Simulator")
    ap.add_argument("root", nargs="?", default="./data",
                    help="каталог JSON-базы (по умолчанию ./data)")
    ap.add_argument("--seed", action="store_true",
                    help="заполнить пустую базу демо-данными")
    ap.add_argument("--no-seed", action="store_true",
                    help="не заполнять базу")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    os.makedirs(root, exist_ok=True)

    from cultist_db.storage import Database
    from cultist_db.seed import seed as seed_db
    db = Database(root)

    if not db.categories and not db.sets and not args.no_seed:
        do_seed = args.seed
        if not do_seed:
            # без GUI-вопроса в консольном режиме — молча сидим по умолчанию
            do_seed = True
        if do_seed:
            seed_db(db)

    from cultist_gui.app import App, create_root_window
    root_win = create_root_window()
    App(root_win, db)
    root_win.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
