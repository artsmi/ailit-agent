# Установка — индекс

Канон по установке, префиксам и артефактам после `scripts/install`. Детальные шаги и переменные — в [`../proto/install.md`](../proto/install.md) (SoT), без дублирования длинных сценариев.

| Документ / элемент | Содержание |
|--------------------|------------|
| [`../proto/install.md`](../proto/install.md) | SoT: `scripts/install`, venv/shim, systemd user unit, префиксы `AILIT_*`. |
| [`../../scripts/install`](../../scripts/install) | Исходник сценария установки (shim `ailit`, unit с `ExecStart` на supervisor). |
| [`../start/repository-launch.md`](../start/repository-launch.md) | Связка dev editable и запуска pytest из venv репозитория. |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../proto/INDEX.md`](../proto/INDEX.md).
