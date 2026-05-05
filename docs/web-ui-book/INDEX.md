# Web UI book (брендбук и HTML-референсы)

**Аннотация:** здесь лежат визуальные токены Candy, продуктовая спецификация экранов и три статических HTML-макета для Desktop/Web UI. Нормативный алгоритм памяти и Desktop-трейс — в [`../../context/algorithms/agent-memory/`](../../context/algorithms/agent-memory/); этот каталог — **документация репозитория** для дизайна и вёрстки.

## Связь с публикацией канона

При **публикации или существенном обновлении** документов пакета `context/algorithms/agent-memory/` (в частности [`desktop-realtime-graph-protocol.md`](../../context/algorithms/agent-memory/desktop-realtime-graph-protocol.md) и строк в [`INDEX.md`](../../context/algorithms/agent-memory/INDEX.md) по Desktop) поддерживайте **`docs/web-ui-book/`** в согласованном виде: при смене эталонного stitch-экспорта выполняйте повторное копирование и обновляйте [`SOURCE.md`](SOURCE.md).

## Структура (8 файлов)

| Раздел | Путь | Назначение |
|--------|------|------------|
| Брендбук Candy | [`candy/DESIGN.md`](candy/DESIGN.md) | Токены, принципы визуального стиля |
| Спецификация экранов | [`ai_agent_design_documentation_for_figma_cursor.md`](ai_agent_design_documentation_for_figma_cursor.md) | Пять блоков макета (sidebar, header, чат, граф, analytics) для Figma/Cursor |
| Экран UI library | [`ai_agent_ui_library_candy_style/code.html`](ai_agent_ui_library_candy_style/code.html) | HTML-референс; превью [`screen.png`](ai_agent_ui_library_candy_style/screen.png) |
| Экран графа взаимодействия | [`ai_agent_agent_interaction_graph_candy_style/code.html`](ai_agent_agent_interaction_graph_candy_style/code.html) | Превью [`screen.png`](ai_agent_agent_interaction_graph_candy_style/screen.png) |
| Экран минималистичного чата | [`ai_agent_minimalist_chat_candy_style/code.html`](ai_agent_minimalist_chat_candy_style/code.html) | Превью [`screen.png`](ai_agent_minimalist_chat_candy_style/screen.png) |

## Просмотр

Откройте нужный `code.html` в браузере. Для офлайн-политики см. [`SOURCE.md`](SOURCE.md).
