import React from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import { highlightFromTraceRow, type PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

type GraphNode = {
  id: string;
  label: string;
  level: "A" | "B" | "C" | "D";
  x?: number;
  y?: number;
  z?: number;
  fx?: number;
  fy?: number;
  fz?: number;
};

type GraphLink = {
  id: string;
  source: string;
  target: string;
};

type HighlightState = {
  readonly kind: "pag.search.highlight";
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly reason: string;
  readonly ttlMs: number;
  readonly startedAtMs: number;
};

type ForceGraphData = {
  readonly nodes: GraphNode[];
  readonly links: GraphLink[];
};

const GRAPH_VIEWPORT_MIN_H = 420;

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

function asStr(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
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

function nodeFromPag(n: Record<string, unknown>): GraphNode | null {
  const id: string = asStr(n["node_id"]);
  if (!id) {
    return null;
  }
  const rawLevel: string = asStr(n["level"]);
  const level: GraphNode["level"] =
    rawLevel === "A" || rawLevel === "B" || rawLevel === "C" || rawLevel === "D" ? rawLevel : "B";
  return {
    id,
    label: asStr(n["title"] ?? n["path"] ?? n["node_id"]) || id,
    level
  };
}

function linkFromPag(e: Record<string, unknown>): GraphLink | null {
  const id: string = asStr(e["edge_id"]);
  const source: string = asStr(e["from_node_id"]);
  const target: string = asStr(e["to_node_id"]);
  if (!id || !source || !target) {
    return null;
  }
  return { id, source, target };
}

function coordinateOrZero(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return value;
}

type Mem3dProps = {
  /** Без auto zoom onEngineStop; максимальная площадь под виз (реф 3D как принцип оформления). */
  readonly noInitialAutoZoom?: boolean;
};

export function MemoryGraph3DPage(p: Readonly<Mem3dProps> = {}): React.JSX.Element {
  const { noInitialAutoZoom = true } = p;
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const ref = React.useRef<ForceGraphMethods | undefined>(undefined);
  const hostRef = React.useRef<HTMLDivElement | null>(null);
  const [viewSize, setViewSize] = React.useState<{ w: number; h: number }>({ w: 800, h: 560 });
  const highlightRef = React.useRef<HighlightState | null>(null);
  const highlightFrameRef = React.useRef<number | null>(null);
  const initialFitDoneRef = React.useRef<boolean>(false);
  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [links, setLinks] = React.useState<GraphLink[]>([]);
  const [err, setErr] = React.useState<string | null>(null);

  const ns0: string | null =
    s.selectedProjectIds.length > 0
      ? s.registry.find((proj) => proj.projectId === s.selectedProjectIds[0])?.namespace ?? null
      : s.registry[0]?.namespace ?? null;

  React.useLayoutEffect(() => {
    const el: HTMLDivElement | null = hostRef.current;
    if (!el) {
      return;
    }
    const ro: ResizeObserver = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w: number = Math.max(1, Math.floor(e.contentRect.width));
        const h: number = Math.max(GRAPH_VIEWPORT_MIN_H, Math.floor(e.contentRect.height) || 560);
        setViewSize({ w, h });
      }
    });
    ro.observe(el);
    const r: DOMRect = el.getBoundingClientRect();
    if (r.width) {
      setViewSize({ w: Math.max(1, Math.floor(r.width)), h: Math.max(GRAPH_VIEWPORT_MIN_H, Math.floor(r.height) || 560) });
    }
    return () => ro.disconnect();
  }, []);

  React.useEffect(() => {
    if (!ns0 || !window.ailitDesktop.pagGraphSlice) {
      setErr(ns0 ? "pagGraphSlice недоступен." : null);
      setNodes([]);
      setLinks([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      const r: Awaited<ReturnType<NonNullable<typeof window.ailitDesktop.pagGraphSlice>>> =
        await window.ailitDesktop.pagGraphSlice({
          namespace: ns0,
          level: null,
          nodeLimit: 1000,
          nodeOffset: 0,
          edgeLimit: 1000,
          edgeOffset: 0
        });
      if (cancelled) {
        return;
      }
      if (!r.ok) {
        setErr(r.error);
        setNodes([]);
        setLinks([]);
        return;
      }
      setErr(null);
      setNodes(r.nodes.map(nodeFromPag).filter((x): x is GraphNode => x !== null));
      setLinks(r.edges.map(linkFromPag).filter((x): x is GraphLink => x !== null));
    })();
    return () => {
      cancelled = true;
    };
  }, [ns0]);

  React.useEffect(() => {
    const last: Record<string, unknown> | undefined = s.rawTraceRows[s.rawTraceRows.length - 1];
    if (!last) {
      return;
    }
    const ev: PagSearchHighlightV1 | null = highlightFromTraceRow(last, ns0 ?? "default");
    if (!ev) {
      return;
    }
    highlightRef.current = {
      ...ev,
      startedAtMs: nowMs()
    };
    runHighlightRefreshLoop();
  }, [ns0, s.rawTraceRows]);

  const data: ForceGraphData = React.useMemo(() => {
    if (nodes.length > 0 || links.length > 0) {
      return { nodes, links };
    }
    const mockNodes: GraphNode[] = mockWorkspace.pag.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      level: n.level
    }));
    const mockLinks: GraphLink[] = mockWorkspace.pag.edges.map((e) => ({
      id: e.id,
      source: e.from,
      target: e.to
    }));
    return { nodes: mockNodes, links: mockLinks };
  }, [nodes, links]);

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

  function triggerMockSearchHighlight(): void {
    const h: HighlightState = {
      kind: "pag.search.highlight",
      nodeIds: ["B:tools/ailit/cli.py", "B:tools/agent_core/runtime/broker.py"],
      edgeIds: ["e1", "e2"],
      reason: "mock",
      ttlMs: 3000,
      startedAtMs: nowMs()
    };
    highlightRef.current = h;
    runHighlightRefreshLoop();
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
    if (typeof fg === "undefined") {
      return;
    }

    const nodes: GraphNode[] = data.nodes;
    if (nodes.length === 0) {
      return;
    }

    const center = nodes.reduce(
      (acc, node) => ({
        x: acc.x + coordinateOrZero(node.x),
        y: acc.y + coordinateOrZero(node.y),
        z: acc.z + coordinateOrZero(node.z)
      }),
      { x: 0, y: 0, z: 0 }
    );

    const centerX: number = center.x / nodes.length;
    const centerY: number = center.y / nodes.length;
    const centerZ: number = center.z / nodes.length;

    for (const node of nodes) {
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
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12, minWidth: 0, flex: 1, minHeight: 0 }}>
      <section className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
        <div className="mem3dHeader cardHeader">3D</div>
        <div className="cardBody" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {err ? <div className="errLine" style={{ marginBottom: 8 }}>{err}</div> : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <button className="primaryButton smBtn" type="button" onClick={triggerMockSearchHighlight}>
              Highlight
            </button>
            <button className="primaryButton smBtn" type="button" onClick={focusRoot}>
              Fit
            </button>
          </div>
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
              graphData={data as unknown as { nodes: object[]; links: object[] }}
              backgroundColor="rgba(0,0,0,0)"
              warmupTicks={80}
              cooldownTicks={120}
              d3VelocityDecay={0.9}
              enableNodeDrag={false}
              enableNavigationControls
              nodeLabel={(n: unknown) => {
                const node = n as GraphNode;
                const h: HighlightState | null = highlightRef.current;
                return h !== null && h.nodeIds.includes(node.id)
                  ? `${node.label}\n${node.id}\n${h.reason}`
                  : `${node.label}\n${node.id}`;
              }}
              nodeVal={(n: unknown) => {
                const node = n as GraphNode;
                const { alive, glow } = getGlow();
                const base: number = node.level === "A" ? 9 : node.level === "B" ? 7 : 5;
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                return hot ? base + glow * 10 : base;
              }}
              nodeColor={(n: unknown) => {
                const node = n as GraphNode;
                const { alive } = getGlow();
                const base: string = levelColor(node.level);
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
                if (!hot) {
                  return base;
                }
                return "#ff4fb4";
              }}
              linkWidth={(l: unknown) => {
                const link = l as GraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 1.8 + glow * 4.2 : 0.8;
              }}
              linkColor={(l: unknown) => {
                const link = l as GraphLink;
                const { alive, glow } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                if (hot) {
                  return `rgba(224, 64, 160, ${0.35 + glow * 0.55})`;
                }
                return "rgba(20, 20, 30, 0.12)";
              }}
              linkDirectionalParticles={(l: unknown) => {
                const link = l as GraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 2 : 0;
              }}
              linkDirectionalParticleWidth={(l: unknown) => {
                const link = l as GraphLink;
                const { alive } = getGlow();
                const h: HighlightState | null = highlightRef.current;
                const hot: boolean = alive && h !== null && h.edgeIds.includes(link.id);
                return hot ? 2.5 : 0;
              }}
              onEngineStop={() => {
                if (noInitialAutoZoom) {
                  if (initialFitDoneRef.current) {
                    return;
                  }
                  const fg = ref.current;
                  if (typeof fg === "undefined") {
                    return;
                  }
                  freezeGraphAtCenteredCoordinates();
                  initialFitDoneRef.current = true;
                  return;
                }
                if (initialFitDoneRef.current) {
                  return;
                }
                const fg0 = ref.current;
                if (typeof fg0 === "undefined") {
                  return;
                }
                freezeGraphAtCenteredCoordinates();
                fg0.zoomToFit(650, 90);
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

