import React from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  useEdgesState,
  useNodesState
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getManifestEntry, type AgentManifestV1 } from "../state/agentManifest";

import rawGraphStyles from "./AgentInteractionGraph.module.css";

const graphStyles: Record<string, string> = rawGraphStyles as unknown as Record<string, string>;

export type AgentLinkKey = {
  readonly fromType: string;
  readonly toType: string;
};

type CustomData = {
  readonly label: string;
  readonly sub: string;
  readonly color: string;
  readonly kind: "agent" | "broker";
};

function BrokerNode(p: NodeProps & { data: CustomData }): React.JSX.Element {
  return (
    <div className={graphStyles["nodeBox"]} style={{ boxShadow: `0 0 0 1px ${p.data.color}33` }}>
      <Handle className={graphStyles["hIn"]} id="t" position={Position.Top} type="target" />
      <div className={graphStyles["nodeIcon"]} style={{ color: p.data.color }}>
        ◇
      </div>
      <div className={graphStyles["nodeLabel"]}>{p.data.label}</div>
      <div className={graphStyles["nodeSub"]}>{p.data.sub}</div>
      <Handle className={graphStyles["hOut"]} id="s" position={Position.Bottom} type="source" />
    </div>
  );
}

function AgentNode(p: NodeProps & { data: CustomData }): React.JSX.Element {
  return (
    <div
      className={graphStyles["nodeBox"]}
      style={{ boxShadow: `0 4px 16px ${p.data.color}22, 0 0 0 1px ${p.data.color}2a` }}
    >
      <Handle className={graphStyles["hIn"]} id="t" position={Position.Top} type="target" />
      <div
        className={graphStyles["nodeIcon"]}
        style={{
          color: p.data.color,
          boxShadow: `0 0 0 3px ${p.data.color}18`
        }}
      >
        ●
      </div>
      <div className={graphStyles["badge"]} style={{ color: p.data.color }}>
        {p.data.sub}
      </div>
      <div className={graphStyles["nodeLabel"]}>{p.data.label}</div>
      <Handle className={graphStyles["hOut"]} id="s" position={Position.Bottom} type="source" />
    </div>
  );
}

const defaultTypes: Record<string, React.ComponentType<NodeProps>> = {
  broker: BrokerNode as React.ComponentType<NodeProps>,
  agent: AgentNode as React.ComponentType<NodeProps>
};

function sortTypes(types: readonly string[]): string[] {
  return [...new Set(types)].sort();
}

function circlePos(i: number, n: number, cx: number, cy: number, r: number): { x: number; y: number } {
  if (n <= 0) {
    return { x: cx, y: cy };
  }
  const a: number = (2 * Math.PI * i) / n - Math.PI / 2;
  return { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r };
}

function buildGraph(
  manifest: AgentManifestV1,
  agentTypes: readonly string[],
  links: readonly AgentLinkKey[]
): { nodes: Node<CustomData>[]; edges: Edge[] } {
  const types: string[] = sortTypes([...agentTypes, ...links.flatMap((l) => [l.fromType, l.toType])].filter(Boolean));
  const n: number = types.length;
  const r: number = Math.max(120, 48 + n * 28);
  const cx: number = 400;
  const cy: number = 320;
  const nodes: Node<CustomData>[] = types.map((t, i) => {
    const { x, y } = circlePos(i, n, cx, cy, r);
    const isBroker: boolean = t === "Broker";
    if (isBroker) {
      return {
        id: t,
        type: "broker",
        position: { x, y },
        data: { label: "BROKER", sub: t, color: "var(--candy-accent)", kind: "broker" as const }
      };
    }
    const m = getManifestEntry(manifest, t);
    return {
      id: t,
      type: "agent",
      position: { x, y },
      data: { label: m.displayName, sub: m.agentType, color: m.color, kind: "agent" as const }
    };
  });
  const edges: Edge[] = links.map((lk, i) => ({
    id: `e-${i}-${lk.fromType}-${lk.toType}`,
    source: lk.fromType,
    target: lk.toType,
    sourceHandle: "s",
    targetHandle: "t",
    animated: true,
    style: { stroke: "var(--candy-accent)", strokeWidth: 2, strokeDasharray: "5 4" },
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--candy-accent)" }
  }));
  return { nodes, edges };
}

type Props = {
  readonly manifest: AgentManifestV1;
  readonly agentTypes: readonly string[];
  readonly links: readonly AgentLinkKey[];
  readonly onEdgeSelect: (fromType: string, toType: string) => void;
  readonly onPaneClick?: () => void;
  readonly className?: string;
};

/**
 * Взаимодействия агентов: направленный граф, клик по рёбру ведёт на «Команда».
 */
export function AgentInteractionGraph(p: Props): React.JSX.Element {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CustomData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  React.useEffect(() => {
    const g: { nodes: Node<CustomData>[]; edges: Edge[] } = buildGraph(
      p.manifest,
      p.agentTypes,
      p.links
    );
    setNodes(g.nodes);
    setEdges(g.edges);
  }, [p.agentTypes, p.links, p.manifest, setEdges, setNodes]);

  return (
    <div className={p.className ?? graphStyles["graphWrap"]} role="img" aria-label="Взаимодействия агентов">
      <ReactFlowProvider>
        <ReactFlow
          className={graphStyles["rf"]}
          defaultEdgeOptions={{ interactionWidth: 24 }}
          edges={edges}
          fitView
          maxZoom={1.45}
          minZoom={0.2}
          nodeTypes={defaultTypes}
          nodes={nodes}
          onEdgeClick={(_ev, e) => {
            const src: string = String((e as Edge).source);
            const dst: string = String((e as Edge).target);
            p.onEdgeSelect(src, dst);
          }}
          onEdgesChange={onEdgesChange}
          onNodesChange={onNodesChange}
          onPaneClick={p.onPaneClick}
        >
          <Background className={graphStyles["bg"]} color="var(--candy-border)" gap={20} size={1} />
          <Controls
            className={graphStyles["ctrl"]}
            position="bottom-center"
            showFitView
            showInteractive={false}
            showZoom
          />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
