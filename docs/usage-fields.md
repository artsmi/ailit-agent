# Поля usage и токены (этап O)

Документ описывает, что означают числа в UI `ailit chat`, в JSONL (`model.response`) и в команде `ailit agent usage last`.

## Нормализованный слой (`NormalizedUsage`)

| Поле | Смысл |
|------|--------|
| `input_tokens` | Входные токены запроса (как правило «prompt»). |
| `output_tokens` | Сгенерированные токены ответа. |
| `total_tokens` | Итог, если провайдер отдал поле; иначе может быть `None`. |
| `reasoning_tokens` | Расширенные модели (reasoning), если есть в `usage` или `completion_tokens_details`. |
| `cached_tokens` | Устаревшее единое поле; по возможности используйте `cache_read` / `cache_write`. |
| `cache_read_tokens` | Токены, прочитанные из prompt cache (аналог `cache_read_input_tokens` у Anthropic и др.). |
| `cache_write_tokens` | Запись в prompt cache (`cache_creation_input_tokens` и т.п.). |
| `usage_unknown` | Хвост: неизвестные провайдеру числовые/простые поля не теряются. |

API **не** отдаёт «hit rate» в буквальном виде; при необходимости hit rate считается в UI как отношение накопленных `cache_read_tokens` к сумме запросов (с оговорками по провайдеру).

## События сессии (`SessionRunner`)

В JSONL для `event_type == "model.response"` добавляются:

- `usage` — последний ответ (сериализация `usage_to_diag_dict`);
- `usage_session_totals` — накопление за прогон: `input_tokens`, `output_tokens`, `reasoning_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens` (здесь — сумма in+out для бюджета).

## CLI

```bash
ailit agent usage last
ailit agent usage last --log-file ~/.ailit/ailit-agent-YYYYMMDDTHHMMSSZ.log
```

Формат строк совпадает с логикой `tools/ailit/usage_display.py` (тот же `UsageSummaryPlainTextFormatter`).

## Провайдеры

- **OpenAI-совместимые**: `prompt_tokens`, `completion_tokens`, `total_tokens`; вложенные `prompt_tokens_details.cached_tokens` маппятся в cache read.
- **Anthropic / шлюзы**: часто `cache_read_input_tokens`, `cache_creation_input_tokens` на верхнем уровне `usage`.
- **DeepSeek / др.**: зависит от фактического JSON; неизвестные ключи попадают в `usage_unknown` и в `provider_metadata.usage_unknown_tail` у нормализованного ответа.
