# Глоссарий пакета desktop-stack

> **Аннотация:** минимальные расшифровки терминов из канона чата, trace, PAG rev и IPC; открывать вместе с [`INDEX.md`](INDEX.md).

| Термин | Расшифровка |
|--------|-------------|
| **SoT** | Source of truth: для `chat_logs_enabled` — разбор yaml в main-процессе Electron; renderer держит зеркало значения при старте сессии (`agentMemoryChatLogsFileTargetsEnabledRef`; pair-log `broker_connect` и др. `logD` — только при `current === true`, см. § Current Reality в [`INDEX.md`](INDEX.md)). |
| **PAG** | Граф памяти в Desktop; дельты приходят из trace; **rev** ведётся по namespace. |
| **Rev mismatch** | Нарушение ожидаемой монотонности `last+1` и поля `rev` входящей дельты для того же namespace. |
| **IPC** | Обмен `ipcRenderer.invoke` / `ipcMain.handle` между renderer и main. |
| **CLI slice** | Подпроцесс `ailit memory pag-slice`, вызываемый из main по запросу renderer. |
| **OR-D*** | Идентификаторы требований исходной постановки Cycle D (см. таблицу в [`INDEX.md`](INDEX.md)). |
| **FR*** | Правила классификации сбоев и запретов в этом пакете (failure rules). |
