import { describe, expect, it } from "vitest";

import { applyPagGraphTraceDelta, parsePagGraphTraceDelta } from "./pagGraphTraceDeltas";
import type { MemoryGraphData } from "./memoryGraphState";

describe("pagGraphTraceDeltas", () => {
  it("parsePagGraphTraceDelta из topic.publish", () => {
    const row: Record<string, unknown> = {
      type: "topic.publish",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "pag.node.upsert",
        payload: {
          kind: "pag.node.upsert",
          namespace: "ns-a",
          rev: 4,
          node: {
            node_id: "B:x.py",
            level: "B",
            path: "x.py",
            title: "x",
            kind: "file"
          }
        }
      }
    };
    const d = parsePagGraphTraceDelta(row);
    expect(d).not.toBeNull();
    if (d === null) {
      return;
    }
    expect(d.kind).toBe("pag.node.upsert");
    expect(d.namespace).toBe("ns-a");
    expect(d.rev).toBe(4);
  });

  it("applyPagGraphTraceDelta не требует внешних вызовов pag-slice (чистая функция)", () => {
    const cur: MemoryGraphData = { nodes: [], links: [] };
    const d = parsePagGraphTraceDelta({
      type: "topic.publish",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "pag.node.upsert",
        payload: {
          kind: "pag.node.upsert",
          namespace: "n",
          rev: 1,
          node: {
            node_id: "A:n",
            level: "A",
            path: ".",
            title: "p",
            kind: "project"
          }
        }
      }
    } as Record<string, unknown>);
    expect(d).not.toBeNull();
    if (d === null) {
      return;
    }
    const o: Record<string, number> = {};
    const r = applyPagGraphTraceDelta(cur, d, {}, o);
    expect(r.data.nodes.length).toBe(1);
    expect(o["n"]).toBe(1);
  });
});
