# `ailit desktop`: product/design contract и границы

## Цель

`ailit desktop` — **Linux-only Electron desktop binary**, который запускается командой `ailit desktop` и становится продуктовой заменой `ailit chat`.

## Канонический дизайн

- Канон Candy-дизайна находится вне репозитория: `/home/artem/Desktop/айлит/stitch_example_showcase_system/` (каталог `Desktop/айлит` — все UI-рефы).
- Внутри репозитория источник правды по tokens/правилам — [`BRANDBOOK_CANDY.md`](BRANDBOOK_CANDY.md).

## Ownership: runtime vs UI

### Runtime (source of truth)

- lifecycle supervisor/broker;
- registry агентов и их availability;
- trace rows и durable trace store;
- исполнение tool/session;
- PAG данные/экспорт;
- usage/errors.

### UI (projection)

- человекочитаемая проекция диалога агентов из runtime events;
- layout, navigation, filters, визуальные состояния;
- граф (layout + highlight decay);
- экраны runtime health и recovery hints;
- экраны отчётов и экспорт (MD/JSON).

## Обязательная контрольная точка (mock-first)

До подключения runtime выполняется UX checkpoint:

- UI полностью интерактивный на mock data;
- пользователь смотрит и даёт фиксы;
- только после явного go начинается runtime integration.

## In-scope для Workflow 9 (MVP)

- Electron shell (main/preload/renderer) + typed IPC (renderer без прямых Node API).
- Candy UI shell (маршруты: Чат / Агенты / Проекты / Команда / Память 2D|3D / Отчёты / Runtime; старые пути редиректятся).
- Mock data для 2 проектов + `AgentWork`/`AgentMemory`.
- PAG-only Memory Graph, без KB/knowledge graph.
- Realtime PAG search highlight с затуханием примерно 3 секунды (live-only).
- Экспорт отчёта сессии в Markdown и JSON.
- Динамичность агентов через manifest/registry (UI не hardcode только двух агентов).

## Out-of-scope для G9.0–G9.2

- Любая интеграция с runtime supervisor/broker (это G9.5+ и запрещено до закрытия G9.2 и явного go).
- Любой перенос существующего Streamlit UX в desktop как продуктовый путь.
- KB/memory graph как отдельная сущность в графе (в MVP показываем только PAG).

## Desktop boundaries и безопасность

- Renderer не имеет прямого доступа к Node APIs; всё через preload bridge и явные typed методы.
- Любая потенциально чувствительная информация (raw payload, file body, secrets) по умолчанию **не** является частью UI/экспортов; только summaries/refs, с отдельным debug раскрытием.

## Навигация

- Назад к design index: [`design/INDEX.md`](INDEX.md)
- Назад к оглавлению docs: [`docs/INDEX.md`](../docs/INDEX.md)

