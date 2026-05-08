import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";

import {
  deriveCrossProjectDisplayMode,
  MEM3D_CROSS_PROJECT_MODAL_I18N_KEY,
  type Mem3dCrossProjectResolution
} from "../state/crossProjectDisplayMode";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { type PagSearchHighlightV1 } from "../runtime/pagHighlightFromTrace";
import {
  MemoryGraphForceGraphProjector,
  findCrossNamespaceEdgesAmong,
  filterMemoryGraphToNamespacesUnion,
  sliceMemoryGraphToNamespace
} from "../runtime/memoryGraphForceGraphProjection";
import {
  type MemoryGraphData,
  type MemoryGraphLink,
  type MemoryGraphNode
} from "../runtime/memoryGraphState";
import {
  computeMemoryGraphDataKey,
  formatMemoryGraphNamespaceSetKey
} from "../runtime/memoryGraphDataKey";
import {
  MEM3D_PAG_MAX_NODES,
  PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD,
  PAG_3D_HEAVY_HIGHLIGHT_LINK_PARTICLES,
  PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD
} from "../runtime/pagGraphLimits";
import {
  MEM3D_LINK_PARTICLE_WIDTH_HOT,
  MEM3D_LINK_PARTICLE_WIDTH_NEURON,
  mem3dColdLinkDirectionalParticles,
  mem3dLinkWidth
} from "../runtime/memoryGraph3DLineStyle";
import {
  MEM3D_LINK_EDGE_FALLBACK,
  mem3dHotLinkRgba,
  resolveMem3dLinkEdgeColors,
  type Mem3dLinkEdgeResolved
} from "../runtime/memoryGraph3DResolvedColors";

type HighlightState = PagSearchHighlightV1 & {
  readonly startedAtMs: number;
};

type Mem3dProps = {
  readonly noInitialAutoZoom?: boolean;
};

const GRAPH_VIEWPORT_MIN_H: number = 420;

const EMPTY_MEMORY_GRAPH: MemoryGraphData = { nodes: [], links: [] };

/** OQ2 placeholder (open_questions.md) — согласовать copy до merge UI. */
const OQ2_PAG_MISSING_BANNER: string =
  "База PAG ещё не создана. После появления store.sqlite3 срез подхватится автоматически (placeholder OQ2).";

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

function mem3dForceGraphTestIdForNamespace(ns: string): string {
  const safe: string = ns.replace(/[^a-zA-Z0-9_-]+/g, "_");
  return `mem3d-force-graph-${safe}`;
}

type Mem3dFgPanelProps = {
  readonly panelReactKey: string;
  readonly graphTestId: string;
  readonly width: number;
  readonly height: number;
  readonly graphData: MemoryGraphData;
  readonly heavyGraph: boolean;
  readonly extremeGraph: boolean;
  readonly displayNamespace: string;
  /** В режиме U подсветка берётся по `node.namespace`, иначе по `displayNamespace` панели. */
  readonly usePerNodeNamespaceHighlight: boolean;
  readonly highlightsByNsRef: React.MutableRefObject<Record<string, HighlightState | null>>;
  readonly registerFg: (panelId: string, fg: ForceGraphMethods | undefined) => void;
  readonly panelId: string;
  readonly noInitialAutoZoom: boolean;
  readonly edgeColorsFallback: Mem3dLinkEdgeResolved;
};

function Mem3dForceGraphPanel(p: Readonly<Mem3dFgPanelProps>): React.JSX.Element {
  const innerRef = useRef<ForceGraphMethods | undefined>(undefined);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const initialFitDoneRef = useRef<boolean>(false);
  const graphNodeCountRef = useRef<number>(0);
  const prevGraphNodeCountRef = useRef<number>(-1);
  const [graphEntryPulse, setGraphEntryPulse] = useState<boolean>(false);
  const [localEdgeColors, setLocalEdgeColors] = useState<Mem3dLinkEdgeResolved>(p.edgeColorsFallback);

  useLayoutEffect((): void | (() => void) => {
    p.registerFg(p.panelId, innerRef.current);
    const raf: number = window.requestAnimationFrame((): void => {
      p.registerFg(p.panelId, innerRef.current);
    });
    return (): void => {
      window.cancelAnimationFrame(raf);
      p.registerFg(p.panelId, undefined);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- регистрация fg по panelId/reactKey/размерам графа
  }, [p.panelId, p.registerFg, p.panelReactKey, p.graphData.nodes.length, p.graphData.links.length]);

  useLayoutEffect((): void => {
    const host: HTMLDivElement | null = hostRef.current;
    if (!host) {
      return;
    }
    setLocalEdgeColors(resolveMem3dLinkEdgeColors(host));
  }, [p.edgeColorsFallback, p.width, p.height, p.panelReactKey]);

  useEffect((): void => {
    graphNodeCountRef.current = p.graphData.nodes.length;
  }, [p.graphData.nodes.length]);

  useEffect((): void | (() => void) => {
    const n: number = p.graphData.nodes.length;
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
  }, [p.graphData.nodes.length]);

  function highlightKeyForNode(node: MemoryGraphNode): string {
    if (p.usePerNodeNamespaceHighlight) {
      const ns: string = node.namespace ?? "";
      return ns.length > 0 ? ns : p.displayNamespace;
    }
    return p.displayNamespace;
  }

  function highlightForNode(node: MemoryGraphNode): HighlightState | null {
    const k: string = highlightKeyForNode(node);
    return p.highlightsByNsRef.current[k] ?? null;
  }

  function getGlowForNode(node: MemoryGraphNode): { readonly alive: boolean; readonly glow: number } {
    const h: HighlightState | null = highlightForNode(node);
    const atMs: number = nowMs();
    const alive: boolean = h !== null && isAlive(h, atMs);
    const glow: number = h !== null && alive ? intensity01(h, atMs) : 0;
    return { alive, glow };
  }

  function freezeGraphAtCenteredCoordinates(fg: ForceGraphMethods): void {
    if (p.graphData.nodes.length === 0) {
      return;
    }
    const center = p.graphData.nodes.reduce(
      (acc, node) => ({
        x: acc.x + coordinateOrZero(node.x),
        y: acc.y + coordinateOrZero(node.y),
        z: acc.z + coordinateOrZero(node.z)
      }),
      { x: 0, y: 0, z: 0 }
    );
    const nNodes: number = p.graphData.nodes.length;
    const centerX: number = center.x / nNodes;
    const centerY: number = center.y / nNodes;
    const centerZ: number = center.z / nNodes;
    for (const node of p.graphData.nodes) {
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
    <div
      ref={hostRef}
      data-testid={p.graphTestId}
      className={graphEntryPulse ? "mem3dView mem3dGraphEntryPulse" : "mem3dView"}
      style={{
        flex: 1,
        minWidth: 0,
        minHeight: GRAPH_VIEWPORT_MIN_H,
        borderRadius: 16,
        overflow: "hidden",
        border: "1px solid var(--candy-border)",
        background: "rgba(255,255,255,0.35)"
      }}
    >
      <ForceGraph3D
        key={p.panelReactKey}
        ref={innerRef}
        width={p.width}
        height={p.height}
        graphData={p.graphData as unknown as { nodes: object[]; links: object[] }}
        backgroundColor="rgba(0,0,0,0)"
        warmupTicks={p.extremeGraph ? 24 : p.heavyGraph ? 40 : 80}
        cooldownTicks={p.extremeGraph ? 40 : p.heavyGraph ? 60 : 120}
        d3VelocityDecay={0.9}
        enableNodeDrag={false}
        enableNavigationControls
        nodeLabel={(n: unknown) => {
          const node: MemoryGraphNode = n as MemoryGraphNode;
          const h: HighlightState | null = highlightForNode(node);
          return h !== null && h.nodeIds.includes(node.id)
            ? `${node.label}\n${node.id}\n${h.reason}`
            : `${node.label}\n${node.id}`;
        }}
        nodeVal={(n: unknown) => {
          const node: MemoryGraphNode = n as MemoryGraphNode;
          const { alive, glow } = getGlowForNode(node);
          const base: number = node.level === "A" ? 9 : node.level === "B" ? 7 : 5;
          const h: HighlightState | null = highlightForNode(node);
          const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
          return hot ? base + glow * 10 : base;
        }}
        nodeColor={(n: unknown) => {
          const node: MemoryGraphNode = n as MemoryGraphNode;
          const { alive } = getGlowForNode(node);
          const base: string = levelColor(node.level);
          const h: HighlightState | null = highlightForNode(node);
          const hot: boolean = alive && h !== null && h.nodeIds.includes(node.id);
          return hot ? MEM3D_HOT_NODE : base;
        }}
        linkWidth={(l: unknown) => {
          const link: MemoryGraphLink = l as MemoryGraphLink;
          const sId: string = linkEndpointId(link.source as string | { id?: string } | object);
          const tId: string = linkEndpointId(link.target as string | { id?: string } | object);
          const sn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === sId);
          const tn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === tId);
          const hS: HighlightState | null =
            sn !== undefined ? highlightForNode(sn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hT: HighlightState | null =
            tn !== undefined ? highlightForNode(tn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hPick: HighlightState | null = hS ?? hT;
          let bestGlow: number = 0;
          let bestAlive: boolean = false;
          for (const x of [sn, tn]) {
            if (x === undefined) {
              continue;
            }
            const g: { readonly alive: boolean; readonly glow: number } = getGlowForNode(x);
            if (g.glow > bestGlow) {
              bestGlow = g.glow;
              bestAlive = g.alive;
            }
          }
          const hot: boolean =
            hPick !== null && linkIsHighlightHot(link, hPick, bestAlive) && (sn !== undefined || tn !== undefined);
          return mem3dLinkWidth(hot, bestGlow);
        }}
        linkColor={(l: unknown) => {
          const link: MemoryGraphLink = l as MemoryGraphLink;
          const sId: string = linkEndpointId(link.source as string | { id?: string } | object);
          const tId: string = linkEndpointId(link.target as string | { id?: string } | object);
          const sn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === sId);
          const tn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === tId);
          const hS: HighlightState | null =
            sn !== undefined ? highlightForNode(sn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hT: HighlightState | null =
            tn !== undefined ? highlightForNode(tn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hPick: HighlightState | null = hS ?? hT;
          let bestGlow: number = 0;
          let bestAlive: boolean = false;
          for (const x of [sn, tn]) {
            if (x === undefined) {
              continue;
            }
            const g: { readonly alive: boolean; readonly glow: number } = getGlowForNode(x);
            if (g.glow > bestGlow) {
              bestGlow = g.glow;
              bestAlive = g.alive;
            }
          }
          const hot: boolean =
            hPick !== null && linkIsHighlightHot(link, hPick, bestAlive) && (sn !== undefined || tn !== undefined);
          return hot
            ? mem3dHotLinkRgba(localEdgeColors.hotRgbTriplet, bestGlow)
            : localEdgeColors.defaultCssColor;
        }}
        linkDirectionalParticles={(l: unknown) => {
          const link: MemoryGraphLink = l as MemoryGraphLink;
          const sId: string = linkEndpointId(link.source as string | { id?: string } | object);
          const tId: string = linkEndpointId(link.target as string | { id?: string } | object);
          const sn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === sId);
          const tn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === tId);
          const hS: HighlightState | null =
            sn !== undefined ? highlightForNode(sn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hT: HighlightState | null =
            tn !== undefined ? highlightForNode(tn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hPick: HighlightState | null = hS ?? hT;
          let bestAlive: boolean = false;
          for (const x of [sn, tn]) {
            if (x === undefined) {
              continue;
            }
            const g: { readonly alive: boolean; readonly glow: number } = getGlowForNode(x);
            if (g.alive) {
              bestAlive = true;
            }
          }
          const hot: boolean =
            hPick !== null && linkIsHighlightHot(link, hPick, bestAlive) && (sn !== undefined || tn !== undefined);
          if (!hot) {
            return mem3dColdLinkDirectionalParticles(p.heavyGraph);
          }
          return p.heavyGraph ? PAG_3D_HEAVY_HIGHLIGHT_LINK_PARTICLES : 2;
        }}
        linkDirectionalParticleWidth={(l: unknown) => {
          const link: MemoryGraphLink = l as MemoryGraphLink;
          const sId: string = linkEndpointId(link.source as string | { id?: string } | object);
          const tId: string = linkEndpointId(link.target as string | { id?: string } | object);
          const sn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === sId);
          const tn: MemoryGraphNode | undefined = p.graphData.nodes.find((x) => x.id === tId);
          const hS: HighlightState | null =
            sn !== undefined ? highlightForNode(sn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hT: HighlightState | null =
            tn !== undefined ? highlightForNode(tn) : p.highlightsByNsRef.current[p.displayNamespace] ?? null;
          const hPick: HighlightState | null = hS ?? hT;
          let bestAlive: boolean = false;
          for (const x of [sn, tn]) {
            if (x === undefined) {
              continue;
            }
            const g: { readonly alive: boolean; readonly glow: number } = getGlowForNode(x);
            if (g.alive) {
              bestAlive = true;
            }
          }
          const hot: boolean =
            hPick !== null && linkIsHighlightHot(link, hPick, bestAlive) && (sn !== undefined || tn !== undefined);
          if (hot) {
            return MEM3D_LINK_PARTICLE_WIDTH_HOT;
          }
          return mem3dColdLinkDirectionalParticles(p.heavyGraph) > 0
            ? MEM3D_LINK_PARTICLE_WIDTH_NEURON
            : 0;
        }}
        onEngineStop={() => {
          if (initialFitDoneRef.current) {
            return;
          }
          const fg: ForceGraphMethods | undefined = innerRef.current;
          if (typeof fg === "undefined") {
            return;
          }
          freezeGraphAtCenteredCoordinates(fg);
          if (!p.noInitialAutoZoom) {
            fg.zoomToFit(650, 90);
          }
          initialFitDoneRef.current = true;
        }}
      />
    </div>
  );
}

type LayoutPanelSpec = {
  readonly panelId: string;
  readonly graphTestId: string;
  readonly displayNamespace: string;
  readonly graphData: MemoryGraphData;
  readonly reactKey: string;
};

export function MemoryGraph3DPage(p: Readonly<Mem3dProps> = {}): React.JSX.Element {
  const { noInitialAutoZoom = true } = p;
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const logDesktopGraphDebug: (event: string, detail: Record<string, unknown>) => void = s.logDesktopGraphDebug;
  const mem3dChatId: string = s.chatId;
  const userDecisionTimeoutSConfig: number | undefined = s.desktopConfig?.user_decision_timeout_s;
  const layoutHostRef = useRef<HTMLDivElement | null>(null);
  const highlightsByNsRef = useRef<Record<string, HighlightState | null>>({});
  const highlightFrameRef = useRef<number | null>(null);
  const lastHighlightRefreshMsRef = useRef<number>(0);
  const throttleNodeCountRef = useRef<number>(0);
  const fgRegistryRef = useRef<Map<string, ForceGraphMethods>>(new Map());
  const crossEdgesRef = useRef<readonly MemoryGraphLink[]>([]);
  const fDiagnosticSentRef = useRef<boolean>(false);

  const [viewSize, setViewSize] = useState<{ w: number; h: number }>({
    w: 800,
    h: 560
  });
  const [edgeColorsFallback, setEdgeColorsFallback] = useState<Mem3dLinkEdgeResolved>(MEM3D_LINK_EDGE_FALLBACK);
  const [resolution, setResolution] = useState<Mem3dCrossProjectResolution>("none");
  const [fallbackHiddenCount, setFallbackHiddenCount] = useState<number>(0);

  const snap: ReturnType<typeof useDesktopSession>["pagGraph"]["activeSnapshot"] = s.pagGraph.activeSnapshot;

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

  const projectsKey: string = useMemo((): string => namespaces.join("\u0000"), [namespaces]);

  /** Подпись набора NS для `graphDataKey` / remount (OR-011); порядок в `namespaces` не важен. */
  const memoryGraphNamespaceSetKey: string = useMemo(
    (): string => formatMemoryGraphNamespaceSetKey(namespaces),
    [namespaces]
  );

  const mergedFromSnap: MemoryGraphData = snap?.merged ?? EMPTY_MEMORY_GRAPH;

  const crossEdges: readonly MemoryGraphLink[] = useMemo(
    (): readonly MemoryGraphLink[] => findCrossNamespaceEdgesAmong(mergedFromSnap, namespaces),
    [mergedFromSnap, namespaces]
  );
  crossEdgesRef.current = crossEdges;

  const needsUserModal: boolean = namespaces.length >= 2 && crossEdges.length > 0;

  const unifiedPrimaryNs: string = useMemo((): string => {
    const xs: string[] = [...namespaces].filter((x) => x.length > 0).sort();
    return xs[0] ?? "default";
  }, [namespaces]);

  const layoutKind: "single" | "multi_separate" | "multi_unified" = useMemo((): "single" | "multi_separate" | "multi_unified" => {
    if (namespaces.length <= 1) {
      return "single";
    }
    if (needsUserModal && resolution === "U") {
      return "multi_unified";
    }
    return "multi_separate";
  }, [namespaces.length, needsUserModal, resolution]);

  const graphDataKey: string = useMemo((): string => {
    return computeMemoryGraphDataKey({
      activeSessionId: s.activeSessionId,
      namespaceSetKey: memoryGraphNamespaceSetKey,
      snap:
        snap == null
          ? null
          : {
              loadState: snap.loadState,
              pagDatabasePresent: snap.pagDatabasePresent,
              graphRevByNamespace: snap.graphRevByNamespace
            }
    });
  }, [s.activeSessionId, snap, memoryGraphNamespaceSetKey]);

  const layoutPanels: readonly LayoutPanelSpec[] = useMemo((): readonly LayoutPanelSpec[] => {
    const baseKey: string = `${graphDataKey}::${layoutKind}::${resolution}`;

    if (namespaces.length <= 1) {
      const ns: string = namespaces[0] ?? "default";
      const gd: MemoryGraphData = MemoryGraphForceGraphProjector.project(mergedFromSnap);
      return [
        {
          panelId: `single:${ns}`,
          graphTestId: mem3dForceGraphTestIdForNamespace(ns || "default"),
          displayNamespace: ns,
          graphData: gd,
          reactKey: `${baseKey}::${ns}`
        }
      ];
    }
    if (layoutKind === "multi_unified") {
      const union: MemoryGraphData = filterMemoryGraphToNamespacesUnion(mergedFromSnap, namespaces);
      const gd: MemoryGraphData = MemoryGraphForceGraphProjector.project(union);
      return [
        {
          panelId: "unified",
          graphTestId: "mem3d-force-graph-unified",
          displayNamespace: unifiedPrimaryNs,
          graphData: gd,
          reactKey: `${baseKey}::unified`
        }
      ];
    }
    const out: LayoutPanelSpec[] = [];
    for (const ns of namespaces) {
      if (ns.length === 0) {
        continue;
      }
      const sliced: MemoryGraphData = sliceMemoryGraphToNamespace(mergedFromSnap, ns);
      const gd: MemoryGraphData = MemoryGraphForceGraphProjector.project(sliced);
      out.push({
        panelId: `ns:${ns}`,
        graphTestId: mem3dForceGraphTestIdForNamespace(ns),
        displayNamespace: ns,
        graphData: gd,
        reactKey: `${baseKey}::${ns}`
      });
    }
    return out;
  }, [mergedFromSnap, namespaces, graphDataKey, layoutKind, resolution, unifiedPrimaryNs]);

  throttleNodeCountRef.current = layoutPanels.reduce(
    (m, lp) => Math.max(m, lp.graphData.nodes.length),
    0
  );

  const cpMode = deriveCrossProjectDisplayMode({
    resolution,
    needsUserModal,
    hiddenCrossEdgesCount: fallbackHiddenCount,
    nowMs: nowMs()
  });

  const pageView: "loading" | "error" | "missingPagEmpty" | "missingPagTrace" | "empty" | "ready" = (() => {
    if (snap == null) {
      return "loading";
    }
    if (snap.loadState === "loading" || snap.loadState === "idle") {
      return "loading";
    }
    if (snap.loadState === "error") {
      return "error";
    }
    if (snap.loadState === "ready") {
      if (!snap.pagDatabasePresent) {
        if (mergedFromSnap.nodes.length === 0 && mergedFromSnap.links.length === 0) {
          return "missingPagEmpty";
        }
        return "missingPagTrace";
      }
      if (mergedFromSnap.nodes.length === 0 && mergedFromSnap.links.length === 0) {
        return "empty";
      }
      return "ready";
    }
    return "loading";
  })();

  const err: string | null = ((): string | null => {
    if (snap == null) {
      return null;
    }
    if (snap.loadState === "error") {
      return snap.loadError != null && snap.loadError.length > 0
        ? snap.loadError
        : "Ошибка чтения PAG (БД).";
    }
    if (snap.loadState === "ready" && snap.warnings.length > 0) {
      return snap.warnings.join(" | ");
    }
    return null;
  })();

  const nodeCount: number = mergedFromSnap.nodes.length;
  const heavyGraph: boolean = nodeCount > PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD;
  const extremeGraph: boolean = nodeCount > PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD;

  const nCols: number = Math.max(1, layoutPanels.length);
  const colW: number = Math.max(1, Math.floor(viewSize.w / nCols));

  const registerFg = useCallback((panelId: string, fg: ForceGraphMethods | undefined): void => {
    if (fg === undefined) {
      fgRegistryRef.current.delete(panelId);
    } else {
      fgRegistryRef.current.set(panelId, fg);
    }
  }, []);

  useEffect((): void => {
    setResolution("none");
    setFallbackHiddenCount(0);
    fDiagnosticSentRef.current = false;
  }, [projectsKey]);

  const userDecisionTimeoutMs: number = Math.max(
    1,
    Math.floor((s.desktopConfig?.user_decision_timeout_s ?? 300) * 1000)
  );

  useEffect((): void | (() => void) => {
    if (!needsUserModal || resolution !== "none") {
      return;
    }
    const t: number = window.setTimeout((): void => {
      setResolution("F");
      setFallbackHiddenCount(crossEdgesRef.current.length);
    }, userDecisionTimeoutMs);
    return (): void => {
      window.clearTimeout(t);
    };
  }, [needsUserModal, resolution, userDecisionTimeoutMs, projectsKey]);

  useEffect((): void => {
    if (resolution !== "F" || !needsUserModal) {
      return;
    }
    if (fDiagnosticSentRef.current) {
      return;
    }
    fDiagnosticSentRef.current = true;
    const timeoutS: number = Math.max(1, Math.floor(userDecisionTimeoutSConfig ?? 300));
    const nsForDiag: string = namespaces.length > 0 ? namespaces.join(",") : unifiedPrimaryNs;
    const iso: string = new Date().toISOString();
    logDesktopGraphDebug("cross_project_edge_decision_timeout", {
      ts_utc: iso,
      hidden_cross_edges_count: fallbackHiddenCount,
      timeout_s: timeoutS,
      namespace: nsForDiag
    });
  }, [
    resolution,
    needsUserModal,
    fallbackHiddenCount,
    namespaces,
    mem3dChatId,
    userDecisionTimeoutSConfig,
    logDesktopGraphDebug,
    unifiedPrimaryNs
  ]);

  useLayoutEffect((): void | (() => void) => {
    const el: HTMLDivElement | null = layoutHostRef.current;
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
        const el2: HTMLDivElement | null = layoutHostRef.current;
        if (el2) {
          const w2: number = Math.max(1, Math.floor(el2.clientWidth));
          const h2: number = Math.max(GRAPH_VIEWPORT_MIN_H, Math.floor(el2.clientHeight) || 560);
          if (w2 > 2 && h2 > 2) {
            window.requestAnimationFrame((): void => {
              for (const fg of fgRegistryRef.current.values()) {
                fg.refresh();
              }
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

  useLayoutEffect((): void => {
    const host: HTMLDivElement | null = layoutHostRef.current;
    if (!host) {
      return;
    }
    setEdgeColorsFallback(resolveMem3dLinkEdgeColors(host));
  }, [graphDataKey, viewSize.w, viewSize.h, layoutPanels.length, layoutKind]);

  useLayoutEffect((): void => {
    if (!s.memoryPanelOpen) {
      return;
    }
    if (viewSize.w < 2 || viewSize.h < 2) {
      return;
    }
    if (layoutPanels.every((lp) => lp.graphData.nodes.length === 0)) {
      return;
    }
    window.requestAnimationFrame((): void => {
      for (const fg of fgRegistryRef.current.values()) {
        fg.refresh();
      }
    });
  }, [s.memoryPanelOpen, layoutPanels, viewSize.w, viewSize.h, graphDataKey]);

  useEffect((): void | (() => void) => {
    return (): void => {
      if (highlightFrameRef.current !== null) {
        window.cancelAnimationFrame(highlightFrameRef.current);
      }
    };
  }, []);

  function anyHighlightAlive(atMs: number): boolean {
    for (const k of Object.keys(highlightsByNsRef.current)) {
      const h: HighlightState | null = highlightsByNsRef.current[k] ?? null;
      if (h !== null && isAlive(h, atMs)) {
        return true;
      }
    }
    return false;
  }

  function pruneDeadHighlights(): void {
    const t: number = nowMs();
    for (const k of Object.keys(highlightsByNsRef.current)) {
      const h: HighlightState | null = highlightsByNsRef.current[k] ?? null;
      if (h !== null && !isAlive(h, t)) {
        delete highlightsByNsRef.current[k];
      }
    }
  }

  function runHighlightRefreshLoop(): void {
    if (highlightFrameRef.current !== null) {
      window.cancelAnimationFrame(highlightFrameRef.current);
    }
    const tick = (): void => {
      const n: number = throttleNodeCountRef.current;
      const throttle: boolean = n > PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD;
      const minMs: number = n > PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD ? 96 : 48;
      const fgs: ForceGraphMethods[] = [...fgRegistryRef.current.values()];
      const t: number = nowMs();
      if (fgs.length > 0) {
        if (throttle) {
          if (t - lastHighlightRefreshMsRef.current < minMs) {
            if (anyHighlightAlive(t)) {
              highlightFrameRef.current = window.requestAnimationFrame(tick);
              return;
            }
          } else {
            lastHighlightRefreshMsRef.current = t;
            for (const fg of fgs) {
              fg.refresh();
            }
          }
        } else {
          lastHighlightRefreshMsRef.current = t;
          for (const fg of fgs) {
            fg.refresh();
          }
        }
      }
      if (anyHighlightAlive(nowMs())) {
        highlightFrameRef.current = window.requestAnimationFrame(tick);
        return;
      }
      pruneDeadHighlights();
      for (const fg of fgs) {
        fg.refresh();
      }
      highlightFrameRef.current = null;
    };
    highlightFrameRef.current = window.requestAnimationFrame(tick);
  }

  useEffect((): void => {
    if (snap == null) {
      return;
    }
    const hl: Readonly<Record<string, PagSearchHighlightV1 | null>> = snap.searchHighlightsByNamespace;
    const targets: readonly string[] = namespaces.length > 0 ? namespaces : ["default"];
    let any: boolean = false;
    for (const ns of targets) {
      const ev: PagSearchHighlightV1 | null = hl[ns] ?? null;
      if (ev !== null) {
        highlightsByNsRef.current[ns] = { ...ev, startedAtMs: nowMs() };
        any = true;
      } else if (Object.prototype.hasOwnProperty.call(highlightsByNsRef.current, ns)) {
        delete highlightsByNsRef.current[ns];
      }
    }
    if (any) {
      runHighlightRefreshLoop();
    } else {
      for (const fg of fgRegistryRef.current.values()) {
        fg.refresh();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runHighlightRefreshLoop только refs
  }, [snap, namespaces, graphDataKey]);

  function focusRoot(): void {
    for (const fg of fgRegistryRef.current.values()) {
      fg.zoomToFit(650, 90);
    }
  }

  const showCrossModal: boolean = needsUserModal && resolution === "none";

  return (
    <div className="mem3dRoot">
      <section
        className="card"
        style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}
        data-mem3d-cross-pending={cpMode.pending_user_choice ? "true" : "false"}
        data-mem3d-cross-mode={cpMode.mode}
      >
        <div className="mem3dHeader cardHeader">3D</div>
        <div className="cardBody" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {cpMode.mode === "F" && cpMode.hidden_cross_edges_count > 0 ? (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(234, 179, 8, 0.18)",
                border: "1px solid rgba(234, 179, 8, 0.5)"
              }}
            >
              Режим F: истёк таймаут выбора ({String(s.desktopConfig?.user_decision_timeout_s ?? 300)} с). Скрыто
              межпроектных рёбер: {String(cpMode.hidden_cross_edges_count)}.
            </div>
          ) : null}
          {snap != null && snap.atLargeGraphWarning ? (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(234, 179, 8, 0.15)",
                border: "1px solid rgba(234, 179, 8, 0.45)"
              }}
              data-testid="mem3d-max-nodes-warning"
            >
              {snap.warnings.find((w) => w.startsWith("PAG:")) ??
                `PAG: в merged ${String(snap.merged.nodes.length)} нод (>${String(MEM3D_PAG_MAX_NODES)}). Срез тяжёлый; нажмите Refresh.`}
            </div>
          ) : null}
          {pageView === "error" && err != null ? (
            <div className="errLine" style={{ marginBottom: 8 }}>{err}</div>
          ) : null}
          {pageView !== "error" && err != null ? (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(234, 179, 8, 0.12)",
                border: "1px solid rgba(234, 179, 8, 0.35)"
              }}
            >
              {err}
            </div>
          ) : null}
          {(pageView === "missingPagEmpty" || pageView === "missingPagTrace") && (
            <div
              className="errLine"
              style={{
                marginBottom: 8,
                background: "rgba(14, 165, 233, 0.10)",
                border: "1px solid rgba(14, 165, 233, 0.35)"
              }}
            >
              {OQ2_PAG_MISSING_BANNER}
            </div>
          )}
          {pageView === "missingPagTrace" ? (
            <div className="memoryJournalEmpty" style={{ marginBottom: 8 }}>
              <span>Ниже — ноды из trace; срез SQLite PAG ещё отсутствует (OQ2 placeholder).</span>
            </div>
          ) : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <button className="primaryButton smBtn" type="button" onClick={() => s.pagGraph.refreshPagGraph()}>
              Refresh
            </button>
            <button className="primaryButton smBtn" type="button" onClick={focusRoot}>
              Fit
            </button>
          </div>
          {pageView === "loading" ? (
            <div className="memoryJournalEmpty">
              <span>Загружаю PAG для активного workspace...</span>
            </div>
          ) : null}
          {pageView === "empty" ? (
            <div className="memoryJournalEmpty">
              <span>Память пока пуста. Она начнёт расти после запросов AgentWork к AgentMemory.</span>
            </div>
          ) : null}
          {pageView === "missingPagEmpty" ? (
            <div className="memoryJournalEmpty">
              <span>Граф пуст: данные PAG в SQLite ещё не появились; после индексации появится срез из БД (OQ2
              placeholder).</span>
            </div>
          ) : null}
          <div
            ref={layoutHostRef}
            data-testid="mem3d-layout-row"
            style={{
              flex: 1,
              minHeight: GRAPH_VIEWPORT_MIN_H,
              display: "flex",
              flexDirection: "row",
              gap: 8,
              position: "relative"
            }}
          >
            {layoutPanels.map((lp) => (
              <Mem3dForceGraphPanel
                key={lp.reactKey}
                panelReactKey={lp.reactKey}
                graphTestId={lp.graphTestId}
                width={colW}
                height={viewSize.h}
                graphData={lp.graphData}
                heavyGraph={heavyGraph}
                extremeGraph={extremeGraph}
                displayNamespace={lp.displayNamespace}
                usePerNodeNamespaceHighlight={layoutKind === "multi_unified"}
                highlightsByNsRef={highlightsByNsRef}
                registerFg={registerFg}
                panelId={lp.panelId}
                noInitialAutoZoom={noInitialAutoZoom}
                edgeColorsFallback={edgeColorsFallback}
              />
            ))}
            {showCrossModal ? (
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="mem3d-cross-project-title"
                data-testid="mem3d-cross-project-modal"
                data-mem3d-i18n-key={MEM3D_CROSS_PROJECT_MODAL_I18N_KEY}
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "rgba(15, 15, 25, 0.45)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 20,
                  borderRadius: 12
                }}
              >
                <div
                  className="card"
                  style={{ maxWidth: 420, margin: 16, padding: "1rem 1.25rem" }}
                >
                  <h2 id="mem3d-cross-project-title" style={{ marginTop: 0, fontSize: "1.05rem" }}>
                    Межпроектные рёбра
                  </h2>
                  <p style={{ marginBottom: 12, lineHeight: 1.45 }}>
                    Обнаружены рёбра между выбранными namespace. U — один граф с межпроектными связями; S — отдельные
                    графы без них. Без выбора до таймаута будет режим F.
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button className="primaryButton smBtn" type="button" onClick={() => setResolution("U")}>
                      Режим U
                    </button>
                    <button className="primaryButton smBtn" type="button" onClick={() => setResolution("S")}>
                      Режим S
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
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
