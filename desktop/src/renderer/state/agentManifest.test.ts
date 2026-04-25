import { describe, expect, it } from "vitest";

import { agentTypeFromRef, DEFAULT_AGENT_MANIFEST_V1, getManifestEntry } from "./agentManifest";

describe("agentManifest v1", () => {
  it("parses type before colon in refs", () => {
    expect(agentTypeFromRef("AgentWork:chat-a")).toBe("AgentWork");
    expect(agentTypeFromRef("AgentX")).toBe("AgentX");
  });

  it("falls back for unknown agent type without throwing", () => {
    const e: ReturnType<typeof getManifestEntry> = getManifestEntry(DEFAULT_AGENT_MANIFEST_V1, "AgentMystery");
    expect(e.displayName).toBe("AgentMystery");
    expect(e.color).toBe("#6b6b6b");
  });

  it("includes seed AgentDummy for extensibility", () => {
    const t: string[] = DEFAULT_AGENT_MANIFEST_V1.entries.map((x) => x.agentType);
    expect(t).toContain("AgentDummy");
  });
});
