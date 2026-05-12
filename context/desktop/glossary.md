# Глоссарий пакета `context/desktop/`

> **Аннотация:** расшифровки сокращений и терминов, встречающихся в [`INDEX.md`](INDEX.md), [`graph-3dmvc.md`](graph-3dmvc.md) и [`realtime-graph-client.md`](realtime-graph-client.md).

## Статус

`approved` — вместе с пакетом **2026-05-12**.

## Термины

| Термин | Значение |
|--------|----------|
| **3dmvc** | Условное имя паттерна: данные памяти сначала нормализуются в **Model/Controller** renderer-процесса; **View** получает только подготовленный **scene graph DTO** и согласованные side-channel данные (например подсветка). |
| **SoT** | Source of truth: авторитетный источник факта; для лимитов slice/UI — код (`pagGraphLimits`, `pag_slice_caps`) и pytest выравнивания, не устаревший markdown. |
| **PAG** | Граф памяти агента в SQLite per-namespace; в UI отображается поле **merged** снимка сессии. |
| **merged** | Собранное представление графа для UI после slice и merge в renderer (**не** один blob «готовый merged» от main). |
| **UC-04A** | Правило проекции: рёбра без обоих концов в текущем множестве id узлов отбрасываются; **не** эквивалентно фильтру узлов степени 0 по **OR-003**. |
| **W14** | Контур команд памяти (в т.ч. подсветка графа через события trace с нормализованной схемой). |
| **primary namespace** | Цепочка для broker handshake по конфигу; **не** означает отбрасывание highlight второго workspace в UI без отдельной политики. |
| **scene graph DTO** | Структура узлов/рёбер и метаданных, допустимая для layout/WebGL после проекции M/C. |
| **graphRevByNamespace** | Монотонный счётчик ревизий графа по namespace; **не** входит в сериализацию React-ключа данных графа (**OR-011**). |
| **D-ORPHAN-A** | Альтернатива **D-ORPHAN-B**: изоляция узлов степени 0 через overlay-only без phantom nodes в node-list; **non-default** до явного слайса в плане/approval. |
| **D-ORPHAN-B** | **Target default** по **OR-003:** перед View удаляются из node-list для WebGL узлы степени 0 в индуцированном подграфе рёбер; подсветка может жить в side-channel. |
| **D-ORPHAN-C** | Waiver-класс: placeholder-узел без рёбер **в** node-list; **запрещён** как default при формулировке OR-003; только с **named waiver** в human approval. |
| **D-MVC-1** | Trace и PAG по IPC обрабатываются в renderer store — это Model/Controller относительно страницы 3D как View. |
| **D-KEY-1** | Политика ключа монтирования графа согласована с `computeMemoryGraphDataKey` без учёта monotonic rev в ключе. |
| **D-CAP-1** | Лимиты узлов/рёбер в UI и slice — **100 000 / 200 000** как в коде и тестах. |
| **D-HI-OWN-1** | SoT подсветки для 3D — snapshot (`searchHighlightsByNamespace` / согласованное поле), не параллельный ad-hoc parse полного trace в View. |
| **D-PERF-1** | Три класса узких мест: линейный trace replay, частые `fg.refresh`, main IPC / `pagGraphSlice` / логирование. |

**Исключение пакета:** если в human approval или в плане внедрения явно зафиксирован слайс `minimal_pack_no_glossary_file`, минимум терминов из этой таблицы дублируется разделом **`## Глоссарий`** внутри [`INDEX.md`](INDEX.md); иначе глоссарий **только** в этом файле.
