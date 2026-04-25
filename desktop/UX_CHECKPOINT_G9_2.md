# G9.2 — UX checkpoint (mock-first) и stop gate

Этот документ фиксирует **UX checkpoint** для `ailit desktop` на mock data (без runtime) и является **stop gate** перед началом runtime integration (G9.5+).

## Что готово в конце G9.1

- Electron main/preload + React/TypeScript renderer.
- Candy UI shell и маршруты:
  - Chat
  - Agent dialogue
  - Current agents
  - Memory Graph (PAG-only mock + highlight decay ~3s)
  - Projects
  - Reports (export mock MD/JSON)
  - Runtime status (mock)
- Runtime integration **не начата** (и запрещена до закрытия G9.2 и явного go).

## Как запустить UX demo (без runtime)

Из корня репозитория:

```bash
cd desktop
npm install
npm run dev
```

Альтернатива (если нужен только build артефакт):

```bash
cd desktop
npm install
npm run build
```

## UX сценарии для показа пользователю

1. **Chat**
   - Видны сообщения user/assistant (mock).
   - Видна плашка mock-first / G9.1.
2. **Reports**
   - Нажать `Export Markdown` → скачивается `.md`.
   - Нажать `Export JSON` → скачивается `.json`.
3. **Agent dialogue**
   - Видна человекочитаемая лента Work ↔ Memory.
   - Raw JSON не доминирует (в mock нет raw panel).
4. **Current agents**
   - Два агента (`AgentWork`, `AgentMemory`) + связь Work→Memory.
5. **Memory Graph**
   - Нажать `Trigger search highlight`.
   - Подсветка узлов/рёбер заметна и затухает примерно за 3 секунды.
6. **Projects**
   - Два проекта, оба active (mock).
7. **Runtime status**
   - Явно отображается mock-only статус и подсказки команд для systemd (placeholder).

## Что собираем в feedback

- UX/brand замечания: читаемость, отступы, контраст, поведение навигации.
- Порядок пунктов меню и названия секций.
- Нужные элементы на top bar (active projects, chat id, status).
- Визуальная заметность highlight decay.

## Stop gate

**Runtime integration не разрешена**, пока пользователь явно не подтвердит go после просмотра демо и фиксов.

Фраза-канон для следующего шага (после подтверждения пользователем):

> G9.2 UX checkpoint закрыт, runtime integration разрешён.

Если go не получен:

> G9.2 UX checkpoint закрыт, runtime integration **не** разрешён.

