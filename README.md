# Cultist Card Manager

Интерактивный десктопный менеджер-редактор игровых карт в стиле **Cultist Simulator**
(Python 3.10+, Tkinter + tkinterdnd2). Данные хранятся в **JSON** на диске в древовидной
структуре каталогов; GUI максимально приближён к визуальному конструктору, активное
использование Drag&Drop.

## Запуск

```bash
pip install tkinterdnd2          # опционально, для «настоящего» DnD
python main.py [путь_к_базе]     # по умолчанию ./data
python main.py --seed            # создать базу и заполнить демо-данными
```

Если `tkinterdnd2` не установлен, приложение работает с graceful-деградацией:
перетаскивание заменяется кнопками `+ − ▲ ▼ +1 -1` и диалогами выбора.

## Структура проекта

| Путь | Назначение |
|---|---|
| `cultist_db/schema.py` | схема карты (все атрибуты CS), типы переиспользуемых атрибутов, slugify/транслит, валидация |
| `cultist_db/storage.py` | JSON-хранилище: дерево категорий → каталоги, наборы → один JSON-файл (один тип элементов в файле), promote локальных атрибутов, usage_count |
| `cultist_db/seed.py` | демо-база (Гроут, Книга Снов, Стук в дверь, Финансирование перевода) |
| `cultist_gui/app.py` | главное окно: дерево слева, вкладки редакторов карт в центре, библиотека атрибутов справа |
| `cultist_gui/tree_panel.py` | древовидная навигация категории/подкатегории/наборы, CRUD, DnD перенос наборов между категориями |
| `cultist_gui/card_editor.py` | визуальный конструктор карты: скалярные поля, drop-зоны для каждого атрибутного списка, предпросмотр карточки |
| `cultist_gui/rule_editor.py` | редактор правил трансмутации (inputs/aspect/duration/result/additional/failure…) |
| `cultist_gui/library_panel.py` | панель переиспользуемых атрибутов — источник drag&drop-элементов |
| `cultist_gui/widgets.py` | DnD-обёртки (payload `APPLICATION/CARTELEMENT`), диалог выбора элемента |

## Модель данных

Категория → подкатегория (деревовидно, отражено каталогами на диске):

```
data/
├── _index.json                  # зеркало дерева (быстрая загрузка)
├── karty/                       # категория «Карты»
│   ├── _cat.json                # метаданные категории
│   ├── osnovnye/startovye-karty.json        # набор = 1 файл = 1 тип элементов
│   └── dopolneniya/istoriya/istoricheskie-karty.json
└── atributy/                    # категория «Атрибуты» (переиспользуемые)
    ├── aspekty/bazovye-aspekty.json
    ├── resursy/materialy.json
    ├── vliyaniya/vliyaniya.json
    └── tsveta-i-ikonki/palitra.json …
```

* Имена каталогов/файлов — транслит кириллицы (`translit.py`).
* Карточные атрибуты: name, description, flavor, subtype (Any/Tool/Lore/Loan/Margin/
  Ingredient/Benefactor/Foe/Location…), level, weight, border, reverse, color, icon;
  списочные: aspects, tags, elements, influences, resources(count/stacks), suppressions,
  hours, properties, emotions, rules; связи used_in/produces/requires/reflects;
  правила трансмутации (inputs, aspect, duration, result, additional, alternative,
  edge_failure, failure, danger).
* **Переиспользуемые атрибуты живут отдельными элементами** в наборах типа
  `aspect/resource/influence/element/suppression/hours/property/emotion/tag/color/icon`.
  Карта ссылается на них: `{"ref": "slug", "count": 2}`. Локально созданный объект
  `{"new": {...}}` при сохранении автоматически **promote-ится** в соответствующий
  набор библиотеки и заменяется ссылкой. Удаление используемого атрибута блокируется
  (`usage_count`).

## Drag&Drop

* элемент библиотеки → drop-зона нужного типа на карте (аспект на аспекты, ресурс на ресурсы…);
* карта из дерева → список связей редактора (requires/used_in/…);
* строка внутри атрибутного списка → реордер; повторный drop существующего counted-ресурса → +1;
* набор из дерева → другая категория (физический перенос JSON-файла);
* Ctrl+S — сохранить активную карту (с promote новых атрибутов).
