/**
 * Единые лимиты PAG для 2D/3D (Workflow 12, D-SCL-1).
 * Согласованы с `loadPagGraphMerged` и `ailit memory pag-slice` /
 * `agent_core.memory.pag_slice_caps`.
 */
export const MEM3D_PAG_MAX_NODES: number = 20_000;
export const MEM3D_PAG_MAX_EDGES: number = 40_000;

/** Порог упрощения 3D (частицы, чаcтота refresh) — см. G12.3 / architecture §9. */
export const PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD: number = 2_000;

/**
 * Выше — дополнительное ужесточение throttling симуляции и cooldown (§9, 20k cap).
 */
export const PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD: number = 12_000;

/**
 * На тяжёлом графе: не выключать «нейрон» на подсвеченных рёбрах — макс. N частиц
 * (G16.3, дёшево).
 */
export const PAG_3D_HEAVY_HIGHLIGHT_LINK_PARTICLES: number = 1;

/**
 * Тяжёлый граф: политика частиц на неспеленных рёбрах (0 — дёшево; не «молча» без константы).
 */
export const PAG_3D_HEAVY_DEFAULT_LINK_PARTICLES: number = 0;

/**
 * Размер одной «страницы» 2D-списка (пагинация UI, не глобальный cap).
 * Глобальные cap — {@link MEM3D_PAG_MAX_NODES} / {@link MEM3D_PAG_MAX_EDGES}.
 */
export const PAG_2D_PAGE_NODE: number = 400;
export const PAG_2D_PAGE_EDGE: number = 400;
