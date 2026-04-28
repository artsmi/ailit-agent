import React from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";

import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { loadPagGraphMerged } from "../runtime/loadPagGraphMerged";
import {
  applyPagGraphTraceDelta,
  parsePagGraphTraceDelta
} from "../runtime/pagGraphTraceDeltas";
import {
  ensureHighlightNodes,
  linkFromPag,
  mergeMemoryGraph,
  nodeFromPag,
  type MemoryGraphData,
  type MemoryGraphLink,
  type MemoryGraphNode
} from "../runtime/memoryGraphState";
import { highlightFromTraceRow, type PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";

type HighlightState = PagSearchHighlightV1 & {
  readonly startedAtMs: number;
};

type Mem3dProps = {
  readonly noInitialAutoZoom?: boolean;
};

const GRAPH_VIEWPORT_MIN_H: number = 420;

function nowMs(): number {
  return Date.now();
}

function isAlive(h: HighlightState, atMs: number): boolean {
  return atMs - h.startedAtMs < h.ttlMs;
}

function intensity01(h: HighlightState, atMs: number): number {
  const dt: number = atMs - h.startedAtMs;
  const t: number = Math.max(0, Math.min(1, dt / h.ttlMs));
  return 1 - t;
}

function coordinateOrZero(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return value;
}

function levelColor(level: "A" | "B" | "C" | "D"): string {
  if (level === "A") {
    return "#e040a0";
  }
  if (level === "B") {
    return "#7c52aa";
  }
  if (level === "D") {
    return "#0ea5e9";
  }
  return "rgba(20, 20, 30, 0.55)";
}

export function MemoryGraph3DPage(p: Readonly<Mem3dProps> = {}): React.JSX.Element {
  const { noInitialAutoZoom = true } = p;
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const ref = React.useRef<ForceGraphMethods | undefined>(undefined);
  const hostRef = React.useRef<HTMLDivElement | null>(null);
  const highlightRef = React.useRef<HighlightState | null>(null);
  const highlightFrameRef = React.useRef<number | null>(null);
  const initialFitDoneRef = React.useRef<boolean>(false);
  const lastTraceRowIndexRef = React.useRef<number>(-1);
  const graphRevByNsRef = React.useRef<Record<string, number>>({});
  const [viewSize, setViewSize] = React.useState<{ w: number; h: number }>({
    w: 800,
    h: 560
  });
  const [graph, setGraph] = React.useState<MemoryGraphData>({
    nodes: [],
    links: []
  });
  const [loadState, setLoadState] = React.useState<"idle" | "loading" | "empty" | "ready" | "error">("idle");
  const [err, setErr] = React.useState<string | null>(null);

  const namespaces: readonly string[] = React.useMemo(() => {
    const ids: readonly string[] =
      s.selectedProjectIds.length > 0
        ? s.selectedProjectIds
        : s.registry.map((proj) => proj.projectId);
    const out: string[] = [];
    for (const id of ids) {
      const ns: string = s.registry.find((proj) => proj.projectId === id)?.namespace ?? "";
      if (ns && !out.includes(ns)) {
        out.push(ns);
      }
    }
    return out;
  }, [s.registry, s.selectedProjectIds]);

  const loadGraph = React.useCallback(async (): Promise<void> => {
    if (namespaces.length === 0 || !window.ailitDesktop.pagGraphSlice) {
      setLoadState(namespaces.length === 0 ? "empty" : "error");
      setErr(namespaces.length === 0 ? null : "pagGraphSlice недоступен.");
      setGraph({ nodes: [], links: [] });
      return;
    }
    setLoadState("loading");
    const slice: typeof window.ailitDesktop.pagGraphSlice = window.ailitDesktop.pagGraphSlice;
    let merged: MemoryGraphData = { nodes: [], links: [] };
    const errors: string[] = [];
    const nextRevs: Record<string, number> = {};
    for (const namespace of namespaces) {
      const r: Awaited<ReturnType<typeof loadPagGraphMerged>> = await loadPagGraphMerged(
        (p) => slice(p),
        { namespace, level: null }
      );
      if (!r.ok) {
        errors.push(`${namespace}: ${r.error}`);
        continue;
      }
      nextRevs[namespace] = r.graphRev;
      merged = mergeMemoryGraph(merged, {
        nodes: r.nodes.map(nodeFromPag).filter((x): x is MemoryGraphNode => x !== null),
        links: r.edges.map(linkFromPag).filter((x): x is MemoryGraphLink => x !== null)
      });
    }
    graphRevByNsRef.current = nextRevs;
    setErr(errors.length > 0 ? errors.join("; ") : null);
    setGraph(merged);
    setLoadState(merged.nodes.length > 0 || merged.links.length > 0 ? "ready" : "empty");
  }, [namespaces, s.activeSessionId]);

  React.useLayoutEffect(() => {
    const el: HTMLDivElement | null = hostRef.current;
    if (!el) {
      return;
    }
    const applySize = (): void => {
      const w: number = Math.max(1, Math.floor(el.clientWidth));
      const h: number = Math.max(
        GRAPH_VIEWPORT_MIN_H,
        Math.floor(el.clientHeight) || 560
      );
      setViewSize({ w, h });
    };
    const ro: ResizeObserver = new ResizeObserver((entries) => {
      if (entries.length > 0) {
        applySize();
      }
    });
    ro.observe(el);
    applySize();
    return () => ro.disconnect();
  }, []);

  React.useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  React.useEffect(() => {
    lastTraceRowIndexRef.current = -1;
    graphRevByNsRef.current = {};
    initialFitDoneRef.current = false;
  }, [s.activeSessionId]);

  React.useEffect(() => {
    const rows: readonly Record<string, unknown>[] = s.rawTraceRows;
    const start: number = lastTraceRowIndexRef.current + 1;
    if (rows.length > 0 && start < rows.length) {
      let revWarn: string | null = null;
      setGraph((cur) => {
        let g: MemoryGraphData = cur;
        const revs: Record<string, number> = { ...graphRevByNsRef.current };
        for (let i: number = start; i < rows.length; i++) {
          const row: Record<string, unknown> = rows[i]! as Record<string, unknown>;
          const d = parsePagGraphTraceDelta(row);
          if (d === null) {
            continue;
          }
          if (!namespaces.includes(d.namespace)) {
            continue;
          }
          const o: Record<string, number> = {};
          const applied: { data: MemoryGraphData; revWarning: string | null } = applyPagGraphTraceDelta(
            g,
            d,
            revs,
            o
          );
          g = applied.data;
          for (const k of Object.keys(o)) {
            const v: number = o[k]!;
            revs[k] = v;
          }
          if (applied.revWarning !== null) {
            revWarn = applied.revWarning;
          }
        }
        graphRevByNsRef.current = revs;
        return g;
      });
      if (revWarn !== null) {
        setErr(revWarn);
      }
      lastTraceRowIndexRef.current = rows.length - 1;
    }
    const last: Record<string, unknown> | undefined = rows[rows.length - 1] as
      | Record<string, unknown>
      | undefined;
    if (!last) {
      return;
    }
    const ev: PagSearchHighlightV1 | null = highlightFromTraceRow(
      last,
      namespaces[0] ?? "default"
    );
    if (!ev) {
      return;
    }
    setGraph((cur) => ensureHighlightNodes(cur, ev.nodeIds, ev.namespace));
    setLoadState("ready");
    highlightRef.current = {
      ...ev,
      startedAtMs: nowMs()
    };
    runHighlightRefreshLoop();
  }, [namespaces, s.rawTraceRows]);

  React.useEffect(() => {
    return () => {
      if (highlightFrameRef.current !== null) {
        window.cancelAnimationFrame(highlightFrameRef.current);
      }
    };
  }, []);

  function getGlow(): { readonly alive: boolean; readonly glow: number } {
    const h: HighlightState | null = highlightRef.current;
    const atMs: number = nowMs();
    const alive: boolean = h !== null && isAlive(h, atMs);
    const glow: number = h !== null && alive ? intensity01(h, atMs) : 0;
    return { alive, glow };
  }

  function runHighlightRefreshLoop(): void {
    if (highlightFrameRef.current !== null) {
      window.cancelAnimationFrame(highlightFrameRef.current);
    }
    const tick = (): void => {
      const fg = ref.current;
      const h: HighlightState | null = highlightRef.current;
      if (typeof fg !== "undefined") {
        fg.refresh();
      }
      if (h !== null && isAlive(h, nowMs())) {
        highlightFrameRef.current = window.requestAnimationFrame(tick);
        return;
      }
      highlightRef.current = null;
      if (typeof fg !== "undefined") {
        fg.refresh();
      }
      highlightFrameRef.current = null;
    };
    highlightFrameRef.current = window.requestAnimationFrame(tick);
  }

  function focusRoot(): void {
    const fg = ref.current;
    if (typeof fg === "undefined") {
      return;
    }
    fg.zoomToFit(650, 90);
  }

  function freezeGraphAtCenteredCoordinates(): void {
    const fg = ref.current;
    if (typeof fg === "undefined" || graph.nodes.length === 0) {
      return;
    }
    const center = graph.nodes.reduce(
      (acc, node) => ({
        x: acc.x + coordinateOrZero(node.x),
        y: acc.y + coordinateOrZero(node.y),
        z: acc.z + coordinateOrZero(node.z)
      }),
      { x: 0, y: 0, z: 0 }
    );
    const centerX: number = center.x / graph.nodes.length;
    const centerY: number = center.y / graph.nodes.length;
    const centerZ: number = center.z / graph.nodes.length;
    for (const node of graph.nodes) {
      const x: number = coordinateOrZero(node.x) - centerX;
      const y: number = coordinateOrZero(node.y) - centerY;
      const z: number = coordinateOrZero(node.z) - centerZ;
      node.x = x;
      node.y = y;
      node.z = z;
      node.fx = x;
      node.fy = y;
      node.fz = z;
    }
    fg.pauseAnimation();
    fg.refresh();
  }

  return (
    <div className="mem3dRoot">
      <section className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
        <div className="mem3dHeader cardHeader">3D</div>
        <div className="cardBody" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {err ? <div className="errLine" style={{ marginBottom: 8 }}>{err}</div> : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <button className="primaryButton smBtn" type="button" onClick={() => void loadGraph()}>
              Refresh
            </button>
            <button className="primaryButton smBtn" type="button" onClick={focusRoot}>
              Fit
            </button>
          </div>
          {loadState === "loading" ? (
            <div className="memoryJournalEmpty">
              <span>Загружаю PAG для активного workspace...</span>
            </div>
          ) : null}
          {loadState === "empty" ? (
            <div className="memoryJournalEmpty">
              <span>Память пока пуста. Она начнёт расти после запросов AgentWork к AgentMemory.</span>
            </div>
          ) : null}
          <div
            ref={hostRef}
            className="mem3dView"
            style={{
              flex: 1,
              minHeight: GRAPH_VIEWPORT_MIN_H,
              borderRadius: 16,
              overflow: "hidden",
              border: "1px solid var(--candy-border)",
              background: "rgba(255,255,255,0.35)"
            }}
          >
            <ForceGraph3D
              ref={ref}
              width={viewSize.w}
              height={viewSize.h}
              graphData={graph as unknown as { nodes: object[]; links: object[] }}
              backgroundColor="rgba(0,0,0,0)"
              warmupTicks={80}
              cooldownTicks={120}
              d3VelocityDecay={0.9}
              enableNodeDrag={false}
              enableNavigationControls
              nodeLabel={(n: unknown) => {
                const node = n as MemoryGraphNode;
                const h: HighlightState | null = highlightRef.current;
                return h !== null && h.nodeIds.includes(node.id)
                  ? `${node.label}\n${node.id}\n${h.reason}`
                  : `${node.label}\n${node.id}`;
              }}
              nodeVal={(n: unknown) => {
                const node = n as MemoryGraphNode;
                const { alive, glow } = getGlow();
                const base: number = node.level === "A" ? 9 : node.level === "B" ? 7 : 5;
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                return hot ? base + glow * 10 : base;
              }}
              nodeColor={(n: unknown) => {
                const node = n as MemoryGraphNode;
                const { alive } = getGlow();
                const base: string = levelColor(node.level);
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                return hot ? "#ff4fb4" : base;
              }}
              linkWidth={(l: unknown) => {
                const link = l as MemoryGraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 1.8 + glow * 4.2 : 0.8;
              }}
              linkColor={(l: unknown) => {
                const link = l as MemoryGraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? `rgba(224, 64, 160, ${0.35 + glow * 0.55})` : "rgba(20, 20, 30, 0.12)";
              }}
              linkDirectionalParticles={(l: unknown) => {
                const link = l as MemoryGraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 2 : 0;
              }}
              linkDirectionalParticleWidth={(l: unknown) => {
                const link = l as MemoryGraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 2.5 : 0;
              }}
              onEngineStop={() => {
                if (initialFitDoneRef.current) {
                  return;
                }
                if (typeof ref.current === "undefined") {
                  return;
                }
                freezeGraphAtCenteredCoordinates();
                if (!noInitialAutoZoom) {
                  ref.current.zoomToFit(650, 90);
                }
                initialFitDoneRef.current = true;
              }}
            />
          </div>
        </div>
      </section>
      <section className="card smLegend">
        <div className="cardBody" style={{ padding: "0.5rem 0.75rem" }}>
          <div className="legendPills" style={{ gap: 6 }}>
            <span className="pill smPill" style={{ background: "rgba(224, 64, 160, 0.10)" }}>
              <span className="fontW800">A</span>
            </span>
            <span className="pill smPill" style={{ background: "rgba(124, 82, 170, 0.10)" }}>
              <span className="fontW800">B</span>
            </span>
            <span className="pill smPill" style={{ background: "rgba(20, 20, 30, 0.06)" }}>
              <span className="fontW800">C</span>
            </span>
            <span className="pill smPill" style={{ background: "rgba(14, 165, 233, 0.10)" }}>
              <span className="fontW800">D</span>
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}
