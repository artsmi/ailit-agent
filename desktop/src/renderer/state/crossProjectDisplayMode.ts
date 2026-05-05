/**
 * Режим отображения межпроектных рёбер в 3D (task 5.1, C-MP-1).
 *
 * U — единый граф по union выбранных namespace (cross-edges видны).
 * S — изолированные графы по namespace (cross-edges скрыты).
 * F — таймаут без ответа: как S + предупреждение + diagnostic line.
 */

export type Mem3dCrossProjectResolution = "none" | "U" | "S" | "F";

export type CrossProjectDisplayMode = {
  readonly mode: "U" | "S" | "F";
  readonly pending_user_choice: boolean;
  readonly hidden_cross_edges_count: number;
  readonly last_updated_ms: number;
};

export const MEM3D_CROSS_PROJECT_MODAL_I18N_KEY: string = "mem3d.cross_project.modal.title";

export function deriveCrossProjectDisplayMode(p: {
  readonly resolution: Mem3dCrossProjectResolution;
  readonly needsUserModal: boolean;
  readonly hiddenCrossEdgesCount: number;
  readonly nowMs: number;
}): CrossProjectDisplayMode {
  if (!p.needsUserModal) {
    return {
      mode: "S",
      pending_user_choice: false,
      hidden_cross_edges_count: 0,
      last_updated_ms: p.nowMs
    };
  }
  if (p.resolution === "none") {
    return {
      mode: "S",
      pending_user_choice: true,
      hidden_cross_edges_count: 0,
      last_updated_ms: p.nowMs
    };
  }
  if (p.resolution === "F") {
    return {
      mode: "F",
      pending_user_choice: false,
      hidden_cross_edges_count: p.hiddenCrossEdgesCount,
      last_updated_ms: p.nowMs
    };
  }
  return {
    mode: p.resolution,
    pending_user_choice: false,
    hidden_cross_edges_count: 0,
    last_updated_ms: p.nowMs
  };
}

