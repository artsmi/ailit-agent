/**
 * D-VIS-1: единые числовые токены толщины рёбер 3D-графа памяти.
 * Дубли literal в `desktop/src/renderer/styles/tokens.css` (--mem3d-link-width-*) — держать в синхроне.
 */
export const MEM3D_LINK_WIDTH_DEFAULT: number = 1.45;

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

/** Ширина сферы «нейрона» на холодном ребре; линия остаётся {@link MEM3D_LINK_WIDTH_DEFAULT}. */
export const MEM3D_LINK_PARTICLE_WIDTH_NEURON: number = 0.65;

/** Одна частица вдоль ребра вне heavy-режима (см. {@link mem3dColdLinkDirectionalParticles}). */
export const MEM3D_LINK_NEURON_PARTICLE_COUNT: number = 1;

export function mem3dLinkWidth(hot: boolean, glow01: number): number {
  if (!hot) {
    return MEM3D_LINK_WIDTH_DEFAULT;
  }
  const g: number = Math.max(0, Math.min(1, glow01));
  return MEM3D_LINK_WIDTH_HOT_BASE + g * MEM3D_LINK_WIDTH_HOT_GLOW_EXTRA;
}

/**
 * UC-07 / лимиты тяжёлого графа: на `heavyGraph` частицы на неспелённых рёбрах выключены (как
 * {@link PAG_3D_HEAVY_DEFAULT_LINK_PARTICLES}), иначе — одна «нейронная» точка.
 */
export function mem3dColdLinkDirectionalParticles(heavyGraph: boolean): number {
  return heavyGraph ? 0 : MEM3D_LINK_NEURON_PARTICLE_COUNT;
}
