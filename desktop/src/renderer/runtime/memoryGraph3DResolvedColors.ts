const RGBA_RE: RegExp =
  /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/i;

export type Mem3dLinkEdgeResolved = {
  readonly defaultCssColor: string;
  readonly hotRgbTriplet: string;
};

/** До первого layout / если probe не сработал — тот же оттенок, что у `--candy-accent` слабый. */
export const MEM3D_LINK_EDGE_FALLBACK: Mem3dLinkEdgeResolved = {
  defaultCssColor: "rgba(224, 64, 160, 0.18)",
  hotRgbTriplet: "224, 64, 160"
};

function parseRgbTriplet(computedColor: string): string | null {
  const m: RegExpMatchArray | null = computedColor.match(RGBA_RE);
  if (m === null) {
    return null;
  }
  return `${m[1]}, ${m[2]}, ${m[3]}`;
}

/**
 * Снимает вычисленный цвет с `color: var(--…)` для WebGL (rgba-строки).
 */
function computedColorFromCssColor(host: HTMLElement, cssColor: string): string {
  const doc: Document = host.ownerDocument;
  const probe: HTMLDivElement = doc.createElement("div");
  probe.setAttribute("data-mem3d-color-probe", "1");
  probe.style.cssText =
    "position:absolute;left:0;top:0;width:0;height:0;overflow:hidden;" +
    "visibility:hidden;pointer-events:none";
  probe.style.color = cssColor;
  host.appendChild(probe);
  const out: string = getComputedStyle(probe).color;
  host.removeChild(probe);
  return out;
}

export function resolveMem3dLinkEdgeColors(host: HTMLElement): Mem3dLinkEdgeResolved {
  const probe: HTMLDivElement = host.ownerDocument.createElement("div");
  probe.setAttribute("data-mem3d-color-probe", "1");
  probe.style.cssText =
    "position:absolute;left:0;top:0;width:0;height:0;overflow:hidden;" +
    "visibility:hidden;pointer-events:none;color:var(--mem3d-link-edge-default)";
  host.appendChild(probe);
  let defaultCssColor: string = getComputedStyle(probe).color;
  if (defaultCssColor.includes("var(")) {
    const raw: string = getComputedStyle(host).getPropertyValue("--mem3d-link-edge-default").trim();
    if (raw !== "") {
      defaultCssColor = computedColorFromCssColor(host, raw);
    }
    if (defaultCssColor.includes("var(") || defaultCssColor === "") {
      defaultCssColor = MEM3D_LINK_EDGE_FALLBACK.defaultCssColor;
    }
  }
  probe.style.color = "var(--candy-accent)";
  const accentComputed: string = getComputedStyle(probe).color;
  host.removeChild(probe);
  const triplet: string | null = parseRgbTriplet(accentComputed);
  const hotRgbTriplet: string = triplet ?? "224, 64, 160";
  return { defaultCssColor, hotRgbTriplet };
}

export function mem3dHotLinkRgba(hotRgbTriplet: string, glow01: number): string {
  const g: number = Math.max(0, Math.min(1, glow01));
  const alpha: number = 0.5 + g * 0.45;
  return `rgba(${hotRgbTriplet}, ${alpha})`;
}
