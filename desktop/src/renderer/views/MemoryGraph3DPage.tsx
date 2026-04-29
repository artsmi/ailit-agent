import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";

import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { highlightFromTraceRow, type PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";
import { type MemoryGraphData, type MemoryGraphLink, type MemoryGraphNode } from "../runtime/memoryGraphState";
import {
  MEM3D_PAG_MAX_NODES,
  PAG_3D_HEAVY_HIGHLIGHT_LINK_PARTICLES,
  PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD
} from "../runtime/pagGraphLimits";

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

/** G16.3: brand-adjacent hot (ярче base levelColor). */
const MEM3D_HOT_NODE: string = "#ff1493";
const MEM3D_HOT_LINK_BASE: string = "255, 20, 147";

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

function linkEndpointId(x: string | { readonly id?: string } | object): string {
  if (typeof x === "string") {
    return x;
  }
  if (x && typeof x === "object" && "id" in x && typeof (x as { id: unknown }).id === "string") {
    return (x as { id: string }).id;
  }
  return String(x);
}

/**
 * Hot link: explicit edge id, или (если edgeIds пуст) ребро между двумя hot-нодами
 * (W14 memory.w14.graph_highlight часто даёт только node_ids).
 */
function linkIsHighlightHot(
  link: MemoryGraphLink,
  h: HighlightState,
  alive: boolean
): boolean {
  if (!alive) {
    return false;
  }
  if (h.edgeIds.length > 0) {
    return h.edgeIds.includes(link.id);
  }
  if (h.nodeIds.length === 0) {
    return false;
  }
  const s: string = linkEndpointId(link.source as string | { id?: string } | object);
  const t: string = linkEndpointId(link.target as string | { id?: string } | object);
  return h.nodeIds.includes(s) && h.nodeIds.includes(t);
}

export function MemoryGraph3DPage(p: Readonly<Mem3dProps> = {}): React.JSX.Element {
  const { noInitialAutoZoom = true } = p;
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const ref = useRef<ForceGraphMethods | undefined>(undefined);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const highlightRef = useRef<HighlightState | null>(null);
  const highlightFrameRef = useRef<number | null>(null);
  const lastHighlightRefreshMsRef = useRef<number>(0);
  const graphNodeCountRef = useRef<number>(0);
  const initialFitDoneRef = useRef<boolean>(false);
  const prevGraphNodeCountRef = useRef<number>(-1);
  const [graphEntryPulse, setGraphEntryPulse] = useState<boolean>(false);
  const [viewSize, setViewSize] = useState<{ w: number; h: number }>({
    w: 800,
    h: 560
  });
  const snap: ReturnType<typeof useDesktopSession>["pagGraph"]["activeSnapshot"] = s.pagGraph.activeSnapshot;
  const graph: MemoryGraphData = snap?.merged ?? { nodes: [], links: [] };
  const graphDataKey: string = useMemo((): string => {
    const st: string = snap?.loadState ?? "none";
    const n: number = graph.nodes.length;
    const rev: string = snap
      ? Object.entries(snap.graphRevByNamespace)
          .map(([k, v]) => `${k}:${String(v)}`)
          .sort()
          .join("|")
      : "";
    return `${s.activeSessionId}-${st}-n${String(n)}-${rev}`;
  }, [s.activeSessionId, snap, graph.nodes.length]);

  const namespaces: readonly string[] = useMemo((): readonly string[] => {
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

  const loadState: "idle" | "loading" | "empty" | "ready" | "error" = (() => {
    if (snap == null) {
      return "loading";
    }
    if (snap.loadState === "loading" || snap.loadState === "idle") {
      return "loading";
    }
    if (snap.loadState === "error") {
      return "error";
    }
    if (graph.nodes.length === 0 && graph.links.length === 0) {
      return "empty";
    }
    return "ready";
  })();

  const err: string | null =
    snap != null
      ? snap.loadError != null
        ? snap.loadError
        : snap.warnings.length > 0
          ? snap.warnings.join(" | ")
          : null
      : null;

  const nodeCount: number = graph.nodes.length;
  const heavyGraph: boolean = nodeCount > PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD;
  const atPagNodeCap: boolean = nodeCount >= MEM3D_PAG_MAX_NODES;

  useEffect((): void => {
    graphNodeCountRef.current = graph.nodes.length;
  }, [graph.nodes.length]);

  useEffect((): void | (() => void) => {
    const n: number = graph.nodes.length;
    const prev: number = prevGraphNodeCountRef.current;
    prevGraphNodeCountRef.current = n;
    if (prev >= 0 && n > prev) {
      setGraphEntryPulse(true);
      const tid: number = window.setTimeout((): void => {
        setGraphEntryPulse(false);
      }, 500);
      return (): void => {
        window.clearTimeout(tid);
      };
    }
    return;
  }, [graph.nodes.length]);

  useEffect((): void => {
    if (s.activeSessionId) {
      initialFitDoneRef.current = false;
    }
  }, [s.activeSessionId]);

  useLayoutEffect((): void | (() => void) => {
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
        const el2: HTMLDivElement | null = hostRef.current;
        if (el2) {
          const w2: number = Math.max(1, Math.floor(el2.clientWidth));
          const h2: number = Math.max(GRAPH_VIEWPORT_MIN_H, Math.floor(el2.clientHeight) || 560);
          if (w2 > 2 && h2 > 2) {
            window.requestAnimationFrame((): void => {
              ref.current?.refresh();
            });
          }
        }
      }
    });
    ro.observe(el);
    applySize();
    return (): void => {
      ro.disconnect();
    };
  }, []);

  /** G16.4: PAG/resize — явный refresh WebGL при открытой панели и появившихся нодах. */
  useLayoutEffect((): void => {
    if (!s.memoryPanelOpen) {
      return;
    }
    if (viewSize.w < 2 || viewSize.h < 2) {
      return;
    }
    if (graph.nodes.length === 0) {
      return;
    }
    const fg: ForceGraphMethods | undefined = ref.current;
    if (typeof fg === "undefined") {
      return;
    }
    window.requestAnimationFrame((): void => {
      ref.current?.refresh();
    });
  }, [s.memoryPanelOpen, graph.nodes.length, viewSize.w, viewSize.h, graphDataKey]);

  useEffect((): void | (() => void) => {
    return (): void => {
      if (highlightFrameRef.current !== null) {
        window.cancelAnimationFrame(highlightFrameRef.current);
      }
    };
  }, []);

  useEffect((): void => {
    if (s.rawTraceRows.length === 0) {
      return;
    }
    const last: Record<string, unknown> = s.rawTraceRows[s.rawTraceRows.length - 1]! as Record<string, unknown>;
    const ev: PagSearchHighlightV1 | null = highlightFromTraceRow(last, namespaces[0] ?? "default");
    if (!ev) {
      return;
    }
    highlightRef.current = { ...ev, startedAtMs: nowMs() };
    runHighlightRefreshLoop();
  }, [namespaces, s.rawTraceRows]);

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
    const minMs: number = 48;
    const tick = (): void => {
      const fg = ref.current;
      const h: HighlightState | null = highlightRef.current;
      const n: number = graphNodeCountRef.current;
      const throttle: boolean = n > PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD;
      if (typeof fg !== "undefined") {
        const t: number = nowMs();
        if (throttle) {
          if (t - lastHighlightRefreshMsRef.current < minMs) {
            if (h !== null && isAlive(h, t)) {
              highlightFrameRef.current = window.requestAnimationFrame(tick);
              return;
            }
          } else {
            lastHighlightRefreshMsRef.current = t;
            fg.refresh();
          }
        } else {
          lastHighlightRefreshMsRef.current = t;
          fg.refresh();
        }
      }
      if (h !== null && isAlive(h, nowMs())) {
        highlightFrameRef.current = window.requestAnimationFrame(tick);
        return;
      }
      highlightRef.current = null;
      if (typeof fg !== "undefined") {
        const t2: number = nowMs();
        lastHighlightRefreshMsRef.current = t2;
        fg.refresh();
      }
      highlightFrameRef.current = null;
    };
    highlightFrameRef.current = window.requestAnimationFrame(tick);
  }

  function focusRoot(): void {
    const fg: ForceGraphMethods | undefined = ref.current;
    if (typeof fg === "undefined") {
      return;
    }
    fg.zoomToFit(650, 90);
  }

  function freezeGraphAtCenteredCoordinates(): void {
    const fg: ForceGraphMethods | undefined = ref.current;
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
          {atPagNodeCap || (snap != null && snap.atLargeGraphWarning) ? (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(234, 179, 8, 0.15)",
                border: "1px solid rgba(234, 179, 8, 0.45)"
              }}
            >
              Граф достиг лимита {MEM3D_PAG_MAX_NODES} нод (PAG) или очень велик — нажмите Refresh для согласования
              с БД.
            </div>
          ) : null}
          {err ? <div className="errLine" style={{ marginBottom: 8 }}>{err}</div> : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <button className="primaryButton smBtn" type="button" onClick={() => s.pagGraph.refreshPagGraph()}>
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
          {loadState === "empty" && !err ? (
            <div className="memoryJournalEmpty">
              <span>Память пока пуста. Она начнёт расти после запросов AgentWork к AgentMemory.</span>
            </div>
          ) : null}
          <div
            ref={hostRef}
            className={graphEntryPulse ? "mem3dView mem3dGraphEntryPulse" : "mem3dView"}
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
              key={graphDataKey}
              ref={ref}
              width={viewSize.w}
              height={viewSize.h}
              graphData={graph as unknown as { nodes: object[]; links: object[] }}
              backgroundColor="rgba(0,0,0,0)"
              warmupTicks={heavyGraph ? 40 : 80}
              cooldownTicks={heavyGraph ? 60 : 120}
              d3VelocityDecay={0.9}
              enableNodeDrag={false}
              enableNavigationControls
              nodeLabel={(n: unknown) => {
                const node: MemoryGraphNode = n as MemoryGraphNode;
                const h: HighlightState | null = highlightRef.current;
                return h !== null && h.nodeIds.includes(node.id)
                  ? `${node.label}\n${node.id}\n${h.reason}`
                  : `${node.label}\n${node.id}`;
              }}
              nodeVal={(n: unknown) => {
                const node: MemoryGraphNode = n as MemoryGraphNode;
                const { alive, glow } = getGlow();
                const base: number = node.level === "A" ? 9 : node.level === "B" ? 7 : 5;
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                return hot ? base + glow * 10 : base;
              }}
              nodeColor={(n: unknown) => {
                const node: MemoryGraphNode = n as MemoryGraphNode;
                const { alive } = getGlow();
                const base: string = levelColor(node.level);
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                return hot ? MEM3D_HOT_NODE : base;
              }}
              linkWidth={(l: unknown) => {
                const link: MemoryGraphLink = l as MemoryGraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean =
                  h !== null && linkIsHighlightHot(link, h, alive);
                return hot ? 2.1 + glow * 4.8 : 0.8;
              }}
              linkColor={(l: unknown) => {
                const link: MemoryGraphLink = l as MemoryGraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean =
                  h !== null && linkIsHighlightHot(link, h, alive);
                return hot
                  ? `rgba(${MEM3D_HOT_LINK_BASE}, ${0.5 + glow * 0.45})`
                  : "rgba(20, 20, 30, 0.12)";
              }}
              linkDirectionalParticles={(l: unknown) => {
                const link: MemoryGraphLink = l as MemoryGraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean =
                  h !== null && linkIsHighlightHot(link, h, alive);
                if (!hot) {
                  return 0;
                }
                return heavyGraph
                  ? PAG_3D_HEAVY_HIGHLIGHT_LINK_PARTICLES
                  : 2;
              }}
              linkDirectionalParticleWidth={(l: unknown) => {
                const link: MemoryGraphLink = l as MemoryGraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean =
                  h !== null && linkIsHighlightHot(link, h, alive);
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
