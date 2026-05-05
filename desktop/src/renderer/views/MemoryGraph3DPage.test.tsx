import React from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { MEM3D_CROSS_PROJECT_MODAL_I18N_KEY } from "../state/crossProjectDisplayMode";
import { deriveAgentLinkKeysFromTrace } from "../runtime/agentDialogueProjection";
import {
  desktopSessionReactContext,
  DesktopSessionProvider,
  type DesktopSessionValue
} from "../runtime/DesktopSessionContext";
import {
  buildBrokerMemoryRecallUiPhase,
  RECALL_UI_PHRASE_WHITELIST
} from "../runtime/memoryRecallUiPhaseProjection";
import type { MemoryGraphData } from "../runtime/memoryGraphState";
import type { PagGraphSessionSnapshot } from "../runtime/pagGraphSessionStore";
import { MemoryGraph3DPage } from "./MemoryGraph3DPage";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterAll(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

vi.mock("react-force-graph-3d", () => ({
  __esModule: true,
  default: function MockForceGraph3D(): React.JSX.Element {
    return <div data-testid="mock-force-graph-3d" />;
  }
}));

function buildPagSnapshot(merged: MemoryGraphData): PagGraphSessionSnapshot {
  return {
    merged,
    graphRevByNamespace: { "ns-a": 1, "ns-b": 1 },
    lastAppliedTraceIndex: -1,
    warnings: [],
    atLargeGraphWarning: false,
    pagDatabasePresent: true,
    loadState: "ready",
    loadError: null,
    searchHighlightsByNamespace: {}
  };
}

function buildDesktopSession(overrides: Partial<DesktopSessionValue>): DesktopSessionValue {
  const base: DesktopSessionValue = {
    chatId: "chat-t",
    sessions: [],
    activeSessionId: "ses-t",
    setActiveSessionId: vi.fn(),
    setActiveSessionProjectIds: vi.fn(),
    toggleProject: vi.fn(),
    createNewChatSession: vi.fn(),
    renameSession: vi.fn(),
    removeSession: vi.fn(),
    toolDisplay: "compact",
    setToolDisplay: vi.fn(),
    lastAgentPair: null,
    setLastAgentPair: vi.fn(),
    connection: "idle",
    homeDir: "/tmp",
    desktopConfig: {
      config_path: "/tmp/cfg",
      version: 1,
      max_nodes: 100_000,
      max_edges: 200_000,
      highlight_namespace_policy: "first_selected",
      trace_reconnect_min_ms: 800,
      memory_journal_poll_ms: 2000,
      pag_sqlite_poll_interval_ms: 2500,
      user_decision_timeout_s: 300
    },
    runtimeDir: "/tmp/rt",
    supervisorSummary: null,
    brokerEndpoint: null,
    lastError: null,
    registry: [],
    selectedProjectIds: [],
    rawTraceRows: [],
    normalizedRows: [],
    agentDialogueMessages: [],
    agentLinkKeys: deriveAgentLinkKeysFromTrace([]),
    chatLines: [],
    reconnectAttempt: 0,
    refreshStatus: vi.fn(),
    loadProjects: vi.fn(),
    connectToBroker: vi.fn(),
    sendUserPrompt: vi.fn(),
    resubscribeTrace: vi.fn(),
    agentTurnInProgress: false,
    brokerMemoryRecallPhase: buildBrokerMemoryRecallUiPhase(false, 0),
    requestStopAgent: vi.fn(),
    permModeLabel: null,
    permModeGateId: null,
    submitPermModeChoice: vi.fn(),
    toolApproval: null,
    submitToolApproval: vi.fn(),
    contextFill: null,
    memoryPanelOpen: true,
    memoryPanelTab: "3d",
    memorySplitRatio: 0.5,
    setMemoryPanelOpen: vi.fn(),
    setMemoryPanelTab: vi.fn(),
    setMemorySplitRatio: vi.fn(),
    pagGraph: {
      activeSnapshot: null,
      refreshPagGraph: vi.fn()
    }
  };
  return { ...base, ...overrides };
}

describe("MemoryGraph3DPage", () => {
  it("does not render recall whitelist strings inside mem3dRoot (UC-06)", () => {
    render(
      <MemoryRouter>
        <DesktopSessionProvider>
          <MemoryGraph3DPage />
        </DesktopSessionProvider>
      </MemoryRouter>
    );
    const root: Element | null = document.querySelector(".mem3dRoot");
    expect(root).not.toBeNull();
    const t: string = (root?.textContent ?? "").replace(/\s+/g, " ");
    for (const entry of RECALL_UI_PHRASE_WHITELIST) {
      expect(t).not.toContain(entry.text);
    }
  });

  it("TC-VITEST-LAYOUT-01: два namespace без cross-edges — два mock ForceGraph3D", () => {
    const merged: MemoryGraphData = {
      nodes: [
        { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
        { id: "a2", label: "a2", level: "B", namespace: "ns-a" },
        { id: "b1", label: "b1", level: "B", namespace: "ns-b" },
        { id: "b2", label: "b2", level: "B", namespace: "ns-b" }
      ],
      links: [
        { id: "ea", source: "a1", target: "a2" },
        { id: "eb", source: "b1", target: "b2" }
      ]
    };
    const snap: PagGraphSessionSnapshot = buildPagSnapshot(merged);
    const session: DesktopSessionValue = buildDesktopSession({
      selectedProjectIds: ["p-a", "p-b"],
      registry: [
        { projectId: "p-a", namespace: "ns-a", title: "A", path: "/a", active: true },
        { projectId: "p-b", namespace: "ns-b", title: "B", path: "/b", active: true }
      ],
      pagGraph: { activeSnapshot: snap, refreshPagGraph: vi.fn() }
    });
    render(
      <MemoryRouter>
        <desktopSessionReactContext.Provider value={session}>
          <MemoryGraph3DPage />
        </desktopSessionReactContext.Provider>
      </MemoryRouter>
    );
    const row: HTMLElement = screen.getByTestId("mem3d-layout-row");
    expect(within(row).getAllByTestId("mock-force-graph-3d")).toHaveLength(2);
    expect(within(row).getByTestId("mem3d-force-graph-ns-a")).toBeTruthy();
    expect(within(row).getByTestId("mem3d-force-graph-ns-b")).toBeTruthy();
  });

  it("TC-VITEST-MODE-01: cross-edge — модал и data-mem3d-i18n-key", () => {
    const merged: MemoryGraphData = {
      nodes: [
        { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
        { id: "b1", label: "b1", level: "B", namespace: "ns-b" }
      ],
      links: [{ id: "cross", source: "a1", target: "b1" }]
    };
    const snap: PagGraphSessionSnapshot = buildPagSnapshot(merged);
    const session: DesktopSessionValue = buildDesktopSession({
      selectedProjectIds: ["p-a", "p-b"],
      registry: [
        { projectId: "p-a", namespace: "ns-a", title: "A", path: "/a", active: true },
        { projectId: "p-b", namespace: "ns-b", title: "B", path: "/b", active: true }
      ],
      pagGraph: { activeSnapshot: snap, refreshPagGraph: vi.fn() }
    });
    render(
      <MemoryRouter>
        <desktopSessionReactContext.Provider value={session}>
          <MemoryGraph3DPage />
        </desktopSessionReactContext.Provider>
      </MemoryRouter>
    );
    const modal: HTMLElement = screen.getByTestId("mem3d-cross-project-modal");
    expect(modal).toBeTruthy();
    expect(modal.getAttribute("data-mem3d-i18n-key")).toBe(MEM3D_CROSS_PROJECT_MODAL_I18N_KEY);
    expect(document.querySelector('[data-mem3d-cross-pending="true"]')).not.toBeNull();
  });

  it("TC-VITEST-MODE-02: cross-edge — по истечении user_decision_timeout_s → F, баннер, diagnostic", async () => {
    const userDecisionTimeoutS: number = 4;
    const appendSpy = vi.spyOn(window.ailitDesktop, "appendSessionDiagnostic");

    vi.useFakeTimers();
    try {
      const merged: MemoryGraphData = {
        nodes: [
          { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
          { id: "b1", label: "b1", level: "B", namespace: "ns-b" }
        ],
        links: [{ id: "cross", source: "a1", target: "b1" }]
      };
      const snap: PagGraphSessionSnapshot = buildPagSnapshot(merged);
      const session: DesktopSessionValue = buildDesktopSession({
        selectedProjectIds: ["p-a", "p-b"],
        runtimeDir: "/tmp/rt-mem3d",
        registry: [
          { projectId: "p-a", namespace: "ns-a", title: "A", path: "/a", active: true },
          { projectId: "p-b", namespace: "ns-b", title: "B", path: "/b", active: true }
        ],
        desktopConfig: {
          config_path: "/tmp/cfg",
          version: 1,
          max_nodes: 100_000,
          max_edges: 200_000,
          highlight_namespace_policy: "first_selected",
          trace_reconnect_min_ms: 800,
          memory_journal_poll_ms: 2000,
          pag_sqlite_poll_interval_ms: 2500,
          user_decision_timeout_s: userDecisionTimeoutS
        },
        pagGraph: { activeSnapshot: snap, refreshPagGraph: vi.fn() }
      });
      render(
        <MemoryRouter>
          <desktopSessionReactContext.Provider value={session}>
            <MemoryGraph3DPage />
          </desktopSessionReactContext.Provider>
        </MemoryRouter>
      );

      expect(screen.getByTestId("mem3d-cross-project-modal")).toBeTruthy();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(userDecisionTimeoutS * 1000);
      });

      const section: Element | null = document.querySelector(".mem3dRoot section.card");
      expect(section?.getAttribute("data-mem3d-cross-mode")).toBe("F");
      expect(section?.getAttribute("data-mem3d-cross-pending")).toBe("false");

      expect(screen.queryByTestId("mem3d-cross-project-modal")).toBeNull();

      expect(screen.getByText(new RegExp(`Режим F:.*${String(userDecisionTimeoutS)}`))).toBeTruthy();
      expect(screen.getByText(/Скрыто\s+межпроектных рёбер:\s+1\./)).toBeTruthy();

      expect(appendSpy).toHaveBeenCalledTimes(1);
      const diagArg: unknown = appendSpy.mock.calls[0]?.[0];
      expect(diagArg).toMatchObject({
        runtimeDir: "/tmp/rt-mem3d",
        chatId: "chat-t",
        lines: [expect.stringContaining("event=cross_project_edge_decision_timeout")]
      });
      const lines: unknown = (diagArg as { lines?: readonly string[] }).lines;
      expect(Array.isArray(lines) && lines[0]).toContain("hidden_cross_edges_count=1");
      expect(Array.isArray(lines) && lines[0]).toContain(`timeout_s=${String(userDecisionTimeoutS)}`);
      expect(Array.isArray(lines) && lines[0]).toContain("namespace=ns-a,ns-b");
    } finally {
      vi.useRealTimers();
    }
  });
});
