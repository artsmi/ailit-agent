import { describe, expect, it } from "vitest";

import {
  MEM3D_LINK_WIDTH_DEFAULT,
  MEM3D_LINK_WIDTH_HOT_SELECTED_MAX,
  MEM3D_LINK_WIDTH_THICKNESS_K,
  mem3dLinkWidth
} from "./memoryGraph3DLineStyle";

describe("memoryGraph3DLineStyle (D-VIS-1)", () => {
  it("highlight max толщина не превышает k·default (UC 2.5)", () => {
    expect(MEM3D_LINK_WIDTH_HOT_SELECTED_MAX).toBeLessThanOrEqual(
      MEM3D_LINK_WIDTH_THICKNESS_K * MEM3D_LINK_WIDTH_DEFAULT
    );
    expect(mem3dLinkWidth(true, 0)).toBeLessThanOrEqual(
      MEM3D_LINK_WIDTH_THICKNESS_K * MEM3D_LINK_WIDTH_DEFAULT
    );
    expect(mem3dLinkWidth(true, 1)).toBeLessThanOrEqual(
      MEM3D_LINK_WIDTH_THICKNESS_K * MEM3D_LINK_WIDTH_DEFAULT
    );
  });
});
