import { describe, expect, it } from "vitest";

import { MEM3D_PAG_MAX_EDGES, MEM3D_PAG_MAX_NODES, PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD } from "./pagGraphLimits";

describe("pagGraphLimits", () => {
  it("согласовано с планом Workflow 12 (10k / 20k / heavy threshold)", () => {
    expect(MEM3D_PAG_MAX_NODES).toBe(10_000);
    expect(MEM3D_PAG_MAX_EDGES).toBe(20_000);
    expect(PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD).toBe(2_000);
  });
});
