/**
 * D-VIS-1: единые числовые токены толщины рёбер 3D-графа памяти.
 * Дубли literal в `styles/tokens.css` (--mem3d-link-width-*) — держать в синхроне.
 */
export const MEM3D_LINK_WIDTH_DEFAULT: number = 1;

export const MEM3D_LINK_WIDTH_HOT_BASE: number = 2;

export const MEM3D_LINK_WIDTH_HOT_GLOW_EXTRA: number = 3.5;

/** Верхняя граница толщины подсвеченного ребра при glow = 1. */
export const MEM3D_LINK_WIDTH_HOT_SELECTED_MAX: number =
  MEM3D_LINK_WIDTH_HOT_BASE + MEM3D_LINK_WIDTH_HOT_GLOW_EXTRA;

/**
 * Правило UC 2.5: highlight не «раздувается» сверх k·default (зафиксированный коэффициент).
 */
export const MEM3D_LINK_WIDTH_THICKNESS_K: number = 6;

export const MEM3D_LINK_PARTICLE_WIDTH_HOT: number = 2.5;

export function mem3dLinkWidth(hot: boolean, glow01: number): number {
  if (!hot) {
    return MEM3D_LINK_WIDTH_DEFAULT;
  }
  const g: number = Math.max(0, Math.min(1, glow01));
  return MEM3D_LINK_WIDTH_HOT_BASE + g * MEM3D_LINK_WIDTH_HOT_GLOW_EXTRA;
}
