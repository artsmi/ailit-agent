import React from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import { mockWorkspace } from "../state/mockData";

type GraphNode = {
  id: string;
  label: string;
  level: "A" | "B" | "C";
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
  readonly ttlMs: number;
  readonly startedAtMs: number;
};

type ForceGraphData = {
  readonly nodes: GraphNode[];
  readonly links: GraphLink[];
};

const GRAPH_VIEWPORT_WIDTH = 860;
const GRAPH_VIEWPORT_HEIGHT = 560;

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

function levelColor(level: "A" | "B" | "C"): string {
  if (level === "A") {
    return "#e040a0";
  }
  if (level === "B") {
    return "#7c52aa";
  }
  return "rgba(20, 20, 30, 0.55)";
}

function coordinateOrZero(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return value;
}

export function MemoryGraph3DPage(): React.JSX.Element {
  const ref = React.useRef<ForceGraphMethods | undefined>(undefined);
  const highlightRef = React.useRef<HighlightState | null>(null);
  const highlightFrameRef = React.useRef<number | null>(null);
  const initialFitDoneRef = React.useRef<boolean>(false);

  const data: ForceGraphData = React.useMemo(() => {
    const nodes: GraphNode[] = mockWorkspace.pag.nodes.map((n) => ({ id: n.id, label: n.label, level: n.level }));
    const links: GraphLink[] = mockWorkspace.pag.edges.map((e) => ({ id: e.id, source: e.from, target: e.to }));
    return { nodes, links };
  }, []);

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
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 16, minWidth: 0 }}>
      <section className="card">
        <div className="cardHeader">Memory Graph 3D (force-graph, mock)</div>
        <div className="cardBody">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div className="pill">
              <span>Obsidian-like</span>
              <span className="mono">force layout • ttl≈3s</span>
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <button className="primaryButton" type="button" onClick={triggerMockSearchHighlight}>
                Trigger highlight
              </button>
              <button className="primaryButton" type="button" onClick={focusRoot}>
                Zoom to fit
              </button>
            </div>
          </div>

          <div
            style={{
              marginTop: 16,
              width: GRAPH_VIEWPORT_WIDTH,
              maxWidth: "100%",
              height: GRAPH_VIEWPORT_HEIGHT,
              borderRadius: 16,
              overflow: "hidden",
              border: "1px solid var(--candy-border)",
              background: "rgba(255,255,255,0.35)",
              marginLeft: "auto",
              marginRight: "auto"
            }}
          >
            <ForceGraph3D
              ref={ref}
              width={GRAPH_VIEWPORT_WIDTH}
              height={GRAPH_VIEWPORT_HEIGHT}
              graphData={data as unknown as { nodes: object[]; links: object[] }}
              backgroundColor="rgba(0,0,0,0)"
              warmupTicks={80}
              cooldownTicks={120}
              d3VelocityDecay={0.9}
              enableNodeDrag={false}
              enableNavigationControls
              nodeLabel={(n: unknown) => {
                const node = n as GraphNode;
                return `${node.label}\n${node.id}`;
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
                if (initialFitDoneRef.current) {
                  return;
                }
                const fg = ref.current;
                if (typeof fg === "undefined") {
                  return;
                }
                freezeGraphAtCenteredCoordinates();
                fg.zoomToFit(650, 90);
                initialFitDoneRef.current = true;
              }}
            />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="cardHeader">Legend / notes</div>
        <div className="cardBody">
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span className="pill" style={{ background: "rgba(224, 64, 160, 0.10)" }}>
              <span style={{ fontWeight: 800 }}>A</span>
              <span className="mono">root / entry</span>
            </span>
            <span className="pill" style={{ background: "rgba(124, 82, 170, 0.10)" }}>
              <span style={{ fontWeight: 800 }}>B</span>
              <span className="mono">core files</span>
            </span>
            <span className="pill" style={{ background: "rgba(20, 20, 30, 0.06)" }}>
              <span style={{ fontWeight: 800 }}>C</span>
              <span className="mono">docs / peripheral</span>
            </span>
          </div>
          <div style={{ marginTop: 12 }} className="mono">
            Это mock. В runtime версии источником nodes/edges будет PAG store/export, а highlight-триггеры будут приходить от
            `AgentMemory` search events.
          </div>
        </div>
      </section>
    </div>
  );
}

