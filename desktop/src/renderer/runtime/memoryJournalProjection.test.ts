import { describe, expect, it } from "vitest";

import { projectMemoryJournalRows } from "./memoryJournalProjection";

describe("projectMemoryJournalRows", () => {
  it("filters rows by active chat and keeps structured fields", () => {
    const out = projectMemoryJournalRows(
      [
        {
          created_at: "2026-04-27T00:00:00Z",
          chat_id: "chat-a",
          event_name: "memory.explore.A.finished",
          summary: "selected project",
          namespace: "ns",
          project_id: "proj",
          node_ids: ["A:ns"],
          edge_ids: ["edge-a"],
          payload: { next_action: "explore.B", partial: false }
        },
        {
          created_at: "2026-04-27T00:00:01Z",
          chat_id: "chat-b",
          event_name: "memory.error",
          summary: "skip",
          payload: {}
        }
      ],
      "chat-a"
    );

    expect(out).toHaveLength(1);
    expect(out[0]?.eventName).toBe("memory.explore.A.finished");
    expect(out[0]?.nodeIds).toEqual(["A:ns"]);
    expect(out[0]?.nextAction).toBe("explore.B");
  });
});
