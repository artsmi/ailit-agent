"""Документированный порядок слоёв merge пользовательской конфигурации.

Соответствует :func:`ailit.merged_config.AilitConfigMerger.load` и
переменным окружения в :class:`ailit.merged_config.ProviderEnvOverlay`.

Приоритет merge (нижележащие строки перекрывают верхние):

1. Встроенные defaults (``_default_ailit_config``).
2. Глобальный файл ``<global_config_dir>/config.yaml``.
3. Проектные файлы ``.ailit/config.yaml`` от корня ФС к ``project_root``
   (глубже в дереве каталогов — выше приоритет; см. G.3).
4. Накладка из окружения (ключи API, ``AILIT_RUN_LIVE``).

Глобальные каталоги резолвятся в :mod:`ailit.user_paths` (в т.ч.
``AILIT_HOME``, ``AILIT_CONFIG_DIR``, ``AILIT_STATE_DIR``, XDG).
"""

from __future__ import annotations

from typing import Final

CONFIG_MERGE_LAYER_NAMES: Final[tuple[str, ...]] = (
    "defaults",
    "global_file",
    "project_dot_ailit",
    "environment_overlay",
)
