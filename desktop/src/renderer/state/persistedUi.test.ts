import { beforeEach, describe, expect, it } from "vitest";

import { loadPersistedUi, normalizeMemorySplitRatio, PERSISTED_UI_KEY } from "./persistedUi";

describe("persisted UI memory panel settings", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("clamps memory split ratio", () => {
    expect(normalizeMemorySplitRatio(0.1)).toBe(0.28);
    expect(normalizeMemorySplitRatio(0.8)).toBe(0.72);
    expect(normalizeMemorySplitRatio(0.45)).toBe(0.45);
  });

  it("loads memory defaults from old persisted state", () => {
    localStorage.setItem(
      PERSISTED_UI_KEY,
      JSON.stringify({
        version: 1,
        sessions: [
          {
            id: "s1",
            chatId: "c1",
            label: "Session",
            projectIds: [],
            createdAt: "2026-04-27T00:00:00Z"
          }
        ],
        activeSessionId: "s1",
        lastAgentPair: null,
        toolDisplay: "normal"
      })
    );

    const ui = loadPersistedUi();
    expect(ui.memoryPanelOpen).toBe(false);
    expect(ui.memoryPanelTab).toBe("3d");
    expect(ui.memorySplitRatio).toBe(0.5);
  });
});
