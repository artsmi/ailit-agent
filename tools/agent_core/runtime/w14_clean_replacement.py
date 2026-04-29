"""W14: clean replacement старых PAG/KB (D14R.1–D14R.2).

Нормативный design freeze: артефакты памяти под W14 — fresh stores,
без переноса/апгрейда схем из прежних deb-путей. Runtime AgentMemory/AgentWork.
"""

from __future__ import annotations

# D14R.1: старые БД одноразовые; в W14 нет режима «перенести старую sqlite».
W14_FRESH_MEMORY_STORES_ONLY: bool = True

# D14R.2: client-side legacy поле requested_reads (список путей) отклоняется
# вне legacy adapter (G14R.3) после G14R.0 freeze.
W14_CLEAN_REPLACEMENT_REQUESTED_READS_IN_CLIENT_PAYLOAD_REJECTED: bool = True

# D14R.3/D14R.4: semantic_c_extraction / memory_c_extractor — не SOT для W14
# (отдельные этапы); здесь только флаги-анкоры для статических тестов.
W14_SOURCE_OF_TRUTH_EXCLUDES_LEGACY_C_EXTRACTOR_MODULES: bool = True
