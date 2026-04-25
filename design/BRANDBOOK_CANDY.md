# Candy brandbook для `ailit desktop`

Канонические референсы (вне репозитория):

- `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_design_documentation_for_figma_cursor.md`
- `/home/artem/Desktop/ айлит/stitch_example_showcase_system/candy/DESIGN.md`
- `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html`

## 1) Вайб и принципы

- **Joyful Pop**: ярко, дружелюбно, «конфетно», но читаемо и системно.
- **Card-first UI**: интерфейс состоит из карточек с мягкими тенями.
- **Pill shapes**: кнопки/табы/чипсы — округлые, с выраженным radius.
- **Прозрачная иерархия**: важные действия крупнее и контрастнее.
- **Microinteractions**: hover/press/active-glow, лёгкая «пружина» в анимации.

## 2) Tokens (MVP)

Ниже — минимальный набор tokens для старта. UI должен собираться из этих значений (чтобы менять стиль в одном месте).

### Цвета

- **Brand / Accent**: `#e040a0`
- **Secondary accent**: `#7c52aa`
- **Background**: светлый, тёплый (не чисто белый)
- **Surface / Card**: белый/молочный с лёгкой тенью
- **Text primary**: почти чёрный
- **Text secondary**: серый
- **Border**: очень светлый серый
- **Success / Warning / Error**: читаемые, но не «токсичные»

### Типографика

- **Font family**: DM Sans (fallback: system-ui, sans-serif)
- **Scale (пример)**:
  - Title: 24–28
  - Section header: 16–18
  - Body: 14–16
  - Caption: 12–13
- **Weight**: 400/500/700

### Спейсинг и сетка

- Базовая единица: 4
- Частые шаги: 8 / 12 / 16 / 24
- Layout: sidebar + main content, внутри — cards и list items

### Радиусы

- **Pill**: 999
- **Card**: 16–20
- **Input**: 12–16

### Тени

- Card shadow: мягкая, размазанная; больше blur, меньше spread
- Active glow: accent-colored outer glow для активных элементов/связей

### Motion

- Duration: 120–200ms для hover/press, 240–360ms для переходов
- Easing: лёгкая пружина (например, cubic-bezier с «bouncy» ощущением)
- Highlight decay: ~3000ms (узлы/рёбра PAG)

## 3) Компоненты (правила)

### Кнопки

- Primary: accent background, белый текст, pill radius, заметный hover/press.
- Secondary: светлая поверхность + accent border/текст.
- Dangerous: отдельный error tone, но не доминирует.

### Чипсы/табы

- Используются для фильтров (A/B/C), активных проектов, статусов.
- Активный state: accent background или accent outline + glow.

### Карточки

- Единый стиль: surface + shadow + radius.
- Заголовок карточки всегда выше body; метаданные — caption.

### Chat

- Ленты сообщений (user/assistant) с пузырями/карточками.
- Tool output/trace — раскрываемая секция (не основной текст).

### Agent dialogue

- Timeline/лента сообщений агент↔агент.
- Человекочитаемый текст — основной; raw JSON только под debug expander.

### Memory Graph (PAG)

- Узлы/рёбра читаемы; активная подсветка заметна.
- Highlight: ярко вспыхивает и плавно затухает ~3s; **без** persistence.

## 4) Desktop boundaries

UI **не** встраивает runtime-логику: runtime остаётся source of truth. UI — проекция. Детали границ: [`DESKTOP_BOUNDARIES.md`](DESKTOP_BOUNDARIES.md).

## Навигация

- Назад к design index: [`design/INDEX.md`](INDEX.md)
- Назад к оглавлению docs: [`docs/INDEX.md`](../docs/INDEX.md)

