import { describe, expect, it } from "vitest";

import {
  brokerHandshakePayload,
  MAX_BROKER_WORKSPACE_EXTRAS,
  resolveRegistryProjectChain,
  supervisorCreateOrGetBrokerParamsFromChain,
  type BrokerProjectRow
} from "./brokerHandshakePayload";
import type { ProjectRegistryEntry } from "./ipc";

describe("brokerHandshakePayload (TC-VITEST-MOCK-01)", () => {
  it("single project: primary only, workspace empty", () => {
    const w = brokerHandshakePayload("c1", [{ namespace: "ns1", projectRoot: "/a" }]);
    expect(w.chat_id).toBe("c1");
    expect(w.primary_namespace).toBe("ns1");
    expect(w.primary_project_root).toBe("/a");
    expect(w.workspace).toEqual([]);
  });

  it("three projects: primary + two extras", () => {
    const w = brokerHandshakePayload("c2", [
      { namespace: "p", projectRoot: "/p" },
      { namespace: "e1", projectRoot: "/e1" },
      { namespace: "e2", projectRoot: "/e2" }
    ]);
    expect(w.primary_namespace).toBe("p");
    expect(w.workspace).toHaveLength(2);
    expect(w.workspace[0]).toEqual({ namespace: "e1", project_root: "/e1" });
    expect(w.workspace[1]).toEqual({ namespace: "e2", project_root: "/e2" });
  });

  it(`caps extras at MAX_BROKER_WORKSPACE_EXTRAS (${MAX_BROKER_WORKSPACE_EXTRAS})`, () => {
    const projects: { namespace: string; projectRoot: string }[] = [];
    for (let i = 0; i < 6; i += 1) {
      projects.push({ namespace: `n${i}`, projectRoot: `/r${i}` });
    }
    const w = brokerHandshakePayload("c3", projects);
    expect(w.workspace).toHaveLength(MAX_BROKER_WORKSPACE_EXTRAS);
    expect(w.primary_namespace).toBe("n0");
    expect(w.workspace[MAX_BROKER_WORKSPACE_EXTRAS - 1]?.namespace).toBe(`n${MAX_BROKER_WORKSPACE_EXTRAS}`);
  });

  it("throws on empty ordered list", () => {
    expect(() => brokerHandshakePayload("c0", [])).toThrow(/non-empty/);
  });

  it("supervisorCreateOrGetBrokerParamsFromChain maps to IPC camelCase", () => {
    const chain: readonly BrokerProjectRow[] = [
      { projectId: "a", namespace: "na", projectRoot: "/a" },
      { projectId: "b", namespace: "nb", projectRoot: "/b" }
    ];
    const p = supervisorCreateOrGetBrokerParamsFromChain("chat-x", chain);
    expect(p).toEqual({
      chatId: "chat-x",
      primaryNamespace: "na",
      primaryProjectRoot: "/a",
      workspace: [{ namespace: "nb", projectRoot: "/b" }]
    });
  });
});

describe("resolveRegistryProjectChain", () => {
  const reg: readonly ProjectRegistryEntry[] = [
    {
      projectId: "p1",
      namespace: "ns1",
      title: "A",
      path: "/x/a",
      active: true
    },
    {
      projectId: "p2",
      namespace: "ns2",
      title: "B",
      path: "/x/b",
      active: true
    }
  ];

  it("orders by selectedProjectIds", () => {
    const ch = resolveRegistryProjectChain(reg, ["p2", "p1"], "first_selected");
    expect(ch?.map((r) => r.projectId)).toEqual(["p2", "p1"]);
  });

  it("falls back to first registry entry when selection empty", () => {
    const ch = resolveRegistryProjectChain(reg, [], "first_selected");
    expect(ch?.map((r) => r.projectId)).toEqual(["p1"]);
  });
});
