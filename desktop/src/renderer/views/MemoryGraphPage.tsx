import React from "react";

import type { PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";
import { pagSearchHighlightShallowEqualForGlow } from "../runtime/pagSearchHighlightShallowEqual";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { PagGraph2dListBuilder, type LevelFilter2d } from "../runtime/pagGraph2dSlice";
import type { MemoryGraphNode } from "../runtime/memoryGraphState";
import { MEM3D_PAG_MAX_NODES, PAG_2D_PAGE_EDGE, PAG_2D_PAGE_NODE } from "../runtime/pagGraphLimits";
import { mockWorkspace } from "../state/mockData";

type LiveHighlight = {
  readonly event: PagSearchHighlightV1;
  readonly startedAtMs: number;
};

function nowMs(): number {
  return Date.now();
}

function isAlive(h: LiveHighlight, atMs: number): boolean {
  return atMs - h.startedAtMs < h.event.ttlMs;
}

function intensity01(h: LiveHighlight, atMs: number): number {
  const t: number = Math.max(0, Math.min(1, (atMs - h.startedAtMs) / h.event.ttlMs));
  return 1 - t;
}

export function MemoryGraphPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const [level, setLevel] = React.useState<LevelFilter2d>("all");
  const [nodeOff, setNodeOff] = React.useState(0);
  const [edgeOff, setEdgeOff] = React.useState(0);
  const [, setTick] = React.useState(0);
  const [mockHighlight, setMockHighlight] = React.useState<LiveHighlight | null>(null);
  const [hi, setHi] = React.useState<LiveHighlight | null>(null);
  const lastSnapshotHighlightRef = React.useRef<PagSearchHighlightV1 | null>(null);

  const ns0: string | null =
    s.selectedProjectIds.length > 0
      ? s.registry.find((p) => p.projectId === s.selectedProjectIds[0])?.namespace ?? null
      : s.registry[0]?.namespace ?? null;

  const snap: ReturnType<typeof useDesktopSession>["pagGraph"]["activeSnapshot"] = s.pagGraph.activeSnapshot;
  const displayLive: ReturnType<typeof PagGraph2dListBuilder.build> | null = React.useMemo((): ReturnType<
    typeof PagGraph2dListBuilder.build
  > | null => {
    if (!ns0 || !snap || snap.loadState === "error") {
      return null;
    }
    return PagGraph2dListBuilder.build(snap.merged, ns0, level, nodeOff, edgeOff);
  }, [level, nodeOff, edgeOff, ns0, snap]);

  React.useEffect((): (() => void) | void => {
    const id: number = window.setInterval((): void => {
      setTick((v) => v + 1);
    }, 80);
    return () => {
      window.clearInterval(id);
    };
  }, []);

  React.useEffect((): void => {
    if (!ns0) {
      lastSnapshotHighlightRef.current = null;
      setHi(null);
      return;
    }
    if (!snap || snap.loadState === "error") {
      lastSnapshotHighlightRef.current = null;
      setHi(null);
      return;
    }
    const ev: PagSearchHighlightV1 | null = snap.searchHighlightsByNamespace[ns0] ?? null;
    if (ev === null) {
      lastSnapshotHighlightRef.current = null;
      setHi(null);
      return;
    }
    const prevDto: PagSearchHighlightV1 | null = lastSnapshotHighlightRef.current;
    if (prevDto !== null && pagSearchHighlightShallowEqualForGlow(prevDto, ev)) {
      return;
    }
    lastSnapshotHighlightRef.current = ev;
    setHi({ event: ev, startedAtMs: nowMs() });
  }, [ns0, snap]);

  const at: number = nowMs();
  const useMock: boolean = !ns0;
  const atPagNodeCap2d: boolean = displayLive != null && displayLive.atNamespaceNodeCap;

  const useLive: boolean = Boolean(ns0) && hi != null;
  const liveGlow: number =
    useLive && hi && isAlive(hi, at) ? intensity01(hi, at) : 0;
  const liveIds: Set<string> =
    useLive && hi && isAlive(hi, at) ? new Set(hi.event.nodeIds) : new Set();

  const mockG: number =
    useMock && mockHighlight && isAlive(mockHighlight, at) ? intensity01(mockHighlight, at) : 0;
  const mockIds: Set<string> =
    useMock && mockHighlight && isAlive(mockHighlight, at) ? new Set(mockHighlight.event.nodeIds) : new Set();

  function triggerMockSearchHighlight(): void {
    setMockHighlight({
      event: {
        kind: "pag.search.highlight",
        namespace: "mock",
        nodeIds: ["B:tools/ailit/cli.py", "B:tools/agent_core/runtime/broker.py"],
        edgeIds: [],
        reason: "mock",
        ttlMs: 3000,
        intensity: "strong",
        queryId: null
      },
      startedAtMs: nowMs()
    });
  }

  const errMsg: string | null =
    snap != null
      ? snap.loadError != null
        ? snap.loadError
        : snap.warnings.length > 0
          ? snap.warnings.join(" | ")
          : null
      : null;

  return (
    <div className="grid2 mem2dRoot">
      <section className="card">
        <div className="mem2dHeader cardHeader">2D</div>
        <div className="cardBody">
          {atPagNodeCap2d ? (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(234, 179, 8, 0.15)",
                border: "1px solid rgba(234, 179, 8, 0.45)"
              }}
            >
              Достигнут лимит {MEM3D_PAG_MAX_NODES} нод PAG в текущем срезе (namespace). Используйте Refresh на 3D или
              смену фильтра.
            </div>
          ) : null}
          {errMsg ? <div className="errLine" style={{ marginBottom: 8 }}>{errMsg}</div> : null}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12, alignItems: "center" }}>
            {(["all", "A", "B", "C"] as const).map((lv) => (
              <button
                key={lv}
                className="pill"
                type="button"
                style={level === lv ? { background: "rgba(224,64,160,0.15)" } : {}}
                onClick={() => {
                  setNodeOff(0);
                  setEdgeOff(0);
                  setLevel(lv);
                }}
              >
                {lv}
              </button>
            ))}
            {displayLive != null && displayLive.hasMore.nodes ? (
              <button
                className="pill"
                type="button"
                onClick={() => {
                  setNodeOff((x) => x + PAG_2D_PAGE_NODE);
                }}
              >
                nodes +page
              </button>
            ) : null}
            {nodeOff > 0 ? (
              <button className="pill" type="button" onClick={() => setNodeOff((x) => Math.max(0, x - PAG_2D_PAGE_NODE))}>
                nodes −page
              </button>
            ) : null}
            {displayLive != null && displayLive.hasMore.edges ? (
              <button
                className="pill"
                type="button"
                onClick={() => {
                  setEdgeOff((x) => x + PAG_2D_PAGE_EDGE);
                }}
              >
                edges +page
              </button>
            ) : null}
            {edgeOff > 0 ? (
              <button className="pill" type="button" onClick={() => setEdgeOff((x) => Math.max(0, x - PAG_2D_PAGE_EDGE))}>
                edges −page
              </button>
            ) : null}
            <button
              className="primaryButton smBtn"
              type="button"
              onClick={triggerMockSearchHighlight}
              disabled={!useMock}
            >
              highlight
            </button>
            {!useMock ? (
              <button
                className="primaryButton smBtn"
                type="button"
                onClick={() => {
                  s.pagGraph.refreshPagGraph();
                }}
              >
                Refresh
              </button>
            ) : null}
          </div>
          <div style={{ marginTop: 16 }}>
            {useMock
              ? mockWorkspace.pag.nodes.map((n) => {
                  const nrec: { id: string; label: string; level: string; staleness: string } = {
                    id: n.id,
                    label: n.label,
                    level: n.level,
                    staleness: ""
                  };
                  const isHot: boolean = mockIds.has(nrec.id);
                  const g: number = isHot ? mockG : 0;
                  return (
                    <div
                      key={nrec.id}
                      style={{
                        marginBottom: 10,
                        padding: "10px 12px",
                        borderRadius: 14,
                        border: "1px solid var(--candy-border)",
                        background: "rgba(255,255,255,0.7)",
                        boxShadow: isHot ? `0 0 0 ${3 + g * 8}px rgba(224, 64, 160, ${0.1 + g * 0.35})` : "",
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 750 }}>{nrec.label}</div>
                        {nrec.staleness ? <div className="metaTiny">{nrec.staleness}</div> : null}
                      </div>
                      <div className="pill" style={{ background: "transparent" }}>
                        <span>{nrec.level}</span>
                      </div>
                    </div>
                  );
                })
              : (displayLive != null ? displayLive.nodes : []).map((n: MemoryGraphNode) => {
                  const nrec: { id: string; label: string; level: string; staleness?: string } = {
                    id: n.id,
                    label: n.label,
                    level: n.level,
                    staleness: n.staleness
                  };
                  const isHot: boolean = liveIds.has(nrec.id);
                  const g: number = isHot ? liveGlow : 0;
                  return (
                    <div
                      key={nrec.id}
                      style={{
                        marginBottom: 10,
                        padding: "10px 12px",
                        borderRadius: 14,
                        border: "1px solid var(--candy-border)",
                        background: "rgba(255,255,255,0.7)",
                        boxShadow: isHot ? `0 0 0 ${3 + g * 8}px rgba(224, 64, 160, ${0.1 + g * 0.35})` : "",
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 750 }}>{nrec.label}</div>
                        {nrec.staleness ? <div className="metaTiny">{nrec.staleness}</div> : null}
                      </div>
                      <div className="pill" style={{ background: "transparent" }}>
                        <span>{nrec.level}</span>
                      </div>
                    </div>
                  );
                })}
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Рёбра</div>
        <div className="cardBody">
          {useMock
            ? mockWorkspace.pag.edges.map((e) => {
                const er: { id: string; from: string; to: string; et: string } = {
                  id: e.id,
                  from: e.from,
                  to: e.to,
                  et: ""
                };
                return (
                  <div
                    key={er.id}
                    style={{
                      marginBottom: 10,
                      padding: "10px 12px",
                      borderRadius: 14,
                      border: "1px solid var(--candy-border)",
                      background: "rgba(224, 64, 160, 0.12)"
                    }}
                  >
                    <div style={{ fontWeight: 750, display: "flex" }}>
                      {er.from} → {er.to}
                    </div>
                  </div>
                );
              })
            : (displayLive != null ? displayLive.edges : []).map((e) => {
                const er: { id: string; from: string; to: string; et: string } = {
                  id: e.id,
                  from: e.from,
                  to: e.to,
                  et: e.et
                };
                return (
                  <div
                    key={er.id}
                    style={{
                      marginBottom: 10,
                      padding: "10px 12px",
                      borderRadius: 14,
                      border: "1px solid var(--candy-border)",
                      background: "rgba(224, 64, 160, 0.12)"
                    }}
                  >
                    <div style={{ fontWeight: 750, display: "flex" }}>
                      {er.from} → {er.to}
                    </div>
                    {er.et ? <div className="metaTiny">{er.et}</div> : null}
                  </div>
                );
              })}
        </div>
      </section>
    </div>
  );
}
