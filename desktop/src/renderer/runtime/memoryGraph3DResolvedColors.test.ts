import { beforeEach, describe, expect, it } from "vitest";

import { resolveMem3dLinkEdgeColors } from "./memoryGraph3DResolvedColors";

describe("memoryGraph3DResolvedColors", () => {
  beforeEach((): void => {
    document.documentElement.style.setProperty("--candy-accent", "#e040a0");
  });

  it("resolveMem3dLinkEdgeColors снимает rgb с --candy-accent и default-токена", () => {
    const host: HTMLDivElement = document.createElement("div");
    host.style.setProperty("--mem3d-link-edge-default", "rgba(224, 64, 160, 0.15)");
    document.body.appendChild(host);
    const r = resolveMem3dLinkEdgeColors(host);
    expect(r.hotRgbTriplet).toMatch(/^\d+, \d+, \d+$/);
    expect(r.defaultCssColor).toMatch(/^rgba?\(/);
    document.body.removeChild(host);
  });
});
