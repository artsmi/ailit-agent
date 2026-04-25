import React from "react";

import { highlightFromTraceRow, type PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

type LevelFilter = "all" | "A" | "B" | "C";

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

function asStr(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
}

function nodeLabel(n: Record<string, unknown>): { id: string; label: string; level: string; staleness: string } {
  return {
    id: asStr(n["node_id"]),
    label: asStr(n["title"] ?? n["path"] ?? n["node_id"]),
    level: asStr(n["level"] ?? "?"),
    staleness: asStr(n["staleness_state"] ?? "")
  };
}

function edgeLabel(e: Record<string, unknown>): { id: string; from: string; to: string; et: string } {
  return {
    id: asStr(e["edge_id"]),
    from: asStr(e["from_node_id"]),
    to: asStr(e["to_node_id"]),
    et: asStr(e["edge_type"] ?? e["edge_class"] ?? "")
  };
}

const PAGE_NODE: number = 400;
const PAGE_EDGE: number = 400;

export function MemoryGraphPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const [level, setLevel] = React.useState<LevelFilter>("all");
  const [nodeOff, setNodeOff] = React.useState(0);
  const [edgeOff, setEdgeOff] = React.useState(0);
  const [err, setErr] = React.useState<string | null>(null);
  const [loadState, setLoadState] = React.useState<string | null>(null);
  const [nodes, setNodes] = React.useState<Record<string, unknown>[]>([]);
  const [edges, setEdges] = React.useState<Record<string, unknown>[]>([]);
  const [hasMore, setHasMore] = React.useState({ nodes: false, edges: false });
  const [hi, setHi] = React.useState<LiveHighlight | null>(null);
  const [, tick] = React.useState(0);
  const [mockHighlight, setMockHighlight] = React.useState<LiveHighlight | null>(null);

  const ns0: string | null =
    s.selectedProjectIds.length > 0
      ? s.registry.find((p) => p.projectId === s.selectedProjectIds[0])?.namespace ?? null
      : s.registry[0]?.namespace ?? null;

  React.useEffect(() => {
    const id: number = window.setInterval(() => {
      tick((v) => v + 1);
    }, 80);
    return () => window.clearInterval(id);
  }, []);

  React.useEffect(() => {
    if (!s.rawTraceRows.length) {
      return;
    }
    const last: Record<string, unknown> | undefined = s.rawTraceRows[s.rawTraceRows.length - 1];
    if (!last) {
      return;
    }
    const ev: PagSearchHighlightV1 | null = highlightFromTraceRow(last, ns0 ?? "default");
    if (ev) {
      setHi({ event: ev, startedAtMs: nowMs() });
    }
  }, [ns0, s.rawTraceRows]);

  const loadGraph: () => Promise<void> = React.useCallback(async () => {
    if (!ns0) {
      setErr("Выберите проект в «Проекты»/чате, чтобы знать namespace PAG.");
      setNodes([]);
      setEdges([]);
      return;
    }
    if (!window.ailitDesktop.pagGraphSlice) {
      setErr("pagGraphSlice недоступен (только в Electron).");
      return;
    }
    setErr(null);
    setLoadState("loading");
    const lv: string | null = level === "all" ? null : level;
    const r: Awaited<ReturnType<NonNullable<typeof window.ailitDesktop.pagGraphSlice>>> =
      await window.ailitDesktop.pagGraphSlice({
        namespace: ns0,
        level: lv,
        nodeLimit: PAGE_NODE,
        nodeOffset: nodeOff,
        edgeLimit: PAGE_EDGE,
        edgeOffset: edgeOff
      });
    if (!r.ok) {
      setLoadState(r.code === "missing_db" ? "missing_db" : "error");
      setErr(r.error);
      setNodes([]);
      setEdges([]);
      return;
    }
    setLoadState(r.pag_state);
    setNodes([...r.nodes]);
    setEdges([...r.edges]);
    setHasMore(r.has_more);
  }, [level, nodeOff, edgeOff, ns0]);

  React.useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const at: number = nowMs();
  const useLive: boolean = Boolean(ns0) && s.rawTraceRows.length > 0;
  const liveGlow: number =
    useLive && hi && isAlive(hi, at) ? intensity01(hi, at) : 0;
  const liveIds: Set<string> =
    useLive && hi && isAlive(hi, at) ? new Set(hi.event.nodeIds) : new Set();

  const useMock: boolean = !ns0;
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
        intensity: "strong"
      },
      startedAtMs: nowMs()
    });
  }

  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Memory Graph (PAG only)</div>
        <div className="cardBody">
          {ns0 ? <div className="mono" style={{ marginBottom: 8 }}>namespace: {ns0}</div> : (
            <div className="mono" style={{ marginBottom: 8, color: "var(--candy-text-2)" }}>проект не выбран — мок-граф / подсветка</div>
          )}
          {err ? <div className="mono" style={{ color: "#b71c1c" }}>{err}</div> : null}
          {loadState ? <div className="mono">state: {loadState}</div> : null}
          {useLive ? <div className="mono" style={{ marginTop: 8 }}>live: подсветка из trace ({liveIds.size ? "active" : "idle"})</div> : null}
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
            {hasMore.nodes ? (
              <button
                className="pill"
                type="button"
                onClick={() => {
                  setNodeOff((x) => x + PAGE_NODE);
                }}
              >
                nodes +page
              </button>
            ) : null}
            {nodeOff > 0 ? (
              <button className="pill" type="button" onClick={() => setNodeOff((x) => Math.max(0, x - PAGE_NODE))}>
                nodes −page
              </button>
            ) : null}
            {hasMore.edges ? (
              <button
                className="pill"
                type="button"
                onClick={() => {
                  setEdgeOff((x) => x + PAGE_EDGE);
                }}
              >
                edges +page
              </button>
            ) : null}
            {edgeOff > 0 ? (
              <button className="pill" type="button" onClick={() => setEdgeOff((x) => Math.max(0, x - PAGE_EDGE))}>
                edges −page
              </button>
            ) : null}
            <div className="pill">
              <span>decay</span> <span className="mono">~3s</span>
            </div>
            <button className="primaryButton" type="button" onClick={triggerMockSearchHighlight} disabled={!useMock}>
              mock highlight
            </button>
          </div>
          <div style={{ marginTop: 16 }}>
            {(useMock ? mockWorkspace.pag.nodes : (nodes as unknown as typeof mockWorkspace.pag.nodes)).map((n) => {
              const nrec: { id: string; label: string; level: string; staleness?: string } = useMock
                ? { id: n.id, label: n.label, level: n.level, staleness: "" }
                : (() => {
                    const a = nodeLabel(n as Record<string, unknown>);
                    return { id: a.id, label: a.label, level: a.level, staleness: a.staleness };
                  })();
              const isHot: boolean = useMock ? mockIds.has(nrec.id) : liveIds.has(nrec.id);
              const g: number = isHot ? (useMock ? mockG : liveGlow) : 0;
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
                    <div className="mono">{nrec.id}</div>
                    {nrec.staleness ? <div className="mono" style={{ fontSize: 12 }}>{nrec.staleness}</div> : null}
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
        <div className="cardHeader">Рёбра (лист, лимит)</div>
        <div className="cardBody">
          {(useMock ? mockWorkspace.pag.edges : edges).map((e) => {
            const er: { id: string; from: string; to: string; et: string } = useMock
              ? {
                  id: (e as (typeof mockWorkspace.pag.edges)[0]).id,
                  from: (e as (typeof mockWorkspace.pag.edges)[0]).from,
                  to: (e as (typeof mockWorkspace.pag.edges)[0]).to,
                  et: ""
                }
              : edgeLabel(e as Record<string, unknown>);
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
                <div className="mono">{er.id}</div>
                {!useMock && er.et ? <div className="mono">{er.et}</div> : null}
              </div>
            );
          })}
          <div className="mono" style={{ marginTop: 8 }}>
            KB-граф не отображается. Большой PAG — постраница, фильтр A/B/C, подсветка — только визуально, без хранения.
          </div>
        </div>
      </section>
    </div>
  );
}
