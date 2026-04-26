import React from "react";
import { useNavigate } from "react-router-dom";

import { AgentInteractionGraph, type AgentLinkKey } from "../graph/AgentInteractionGraph";
import { agentTypeFromRef, DEFAULT_AGENT_MANIFEST_V1 } from "../state/agentManifest";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

function uniqueTypesFromContext(liveTypes: ReadonlySet<string>): readonly string[] {
  const mTypes: string[] = DEFAULT_AGENT_MANIFEST_V1.entries.map((e) => e.agentType);
  const merged: Set<string> = new Set([...mTypes, ...liveTypes]);
  return [...merged].sort();
}

function sortU(ids: readonly string[]): string[] {
  return [...new Set(ids.map((x) => String(x)))].sort();
}

/**
 * «Агенты» — граф взаимодействия; ребро → «Команда».
 */
export function CurrentAgentsPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const nav: ReturnType<typeof useNavigate> = useNavigate();
  const fromTrace: Set<string> = new Set();
  for (const r of s.rawTraceRows) {
    for (const k of ["from_agent", "to_agent"] as const) {
      const ref: string = String((r as Record<string, unknown>)[k] ?? "");
      if (ref) {
        const t: string = agentTypeFromRef(ref);
        if (t.startsWith("Agent") || t === "Broker") {
          fromTrace.add(t);
        }
      }
    }
  }
  const useLive: boolean = s.rawTraceRows.length > 0;
  const linkList: readonly AgentLinkKey[] = useLive
    ? s.agentLinkKeys.map((k) => ({ fromType: k.fromType, toType: k.toType }))
    : mockWorkspace.agentLinks.map((l) => ({ fromType: l.fromAgentType, toType: l.toAgentType }));
  const nodeBase: string[] = useLive
    ? [...uniqueTypesFromContext(fromTrace)]
    : [...
        mockWorkspace.agents.map((a) => a.agentType),
        ...["Broker"]
      ];
  const withLinks: string[] = [
    ...nodeBase,
    ...linkList.flatMap((x) => [x.fromType, x.toType] as [string, string])
  ];
  const nodeTypes: string[] = sortU(withLinks);
  if (linkList.length === 0 && nodeTypes.filter((t) => t !== "Broker").length === 0) {
    return (
      <div className="pageSingle">
        <section className="card cardFlush" />
      </div>
    );
  }
  return (
    <div className="pageSingle">
      <section className="card cardFlush">
        <div className="pageTitleRow">
          <h1 className="sectionTitle">Агенты</h1>
        </div>
        <div className="graphPad">
          <AgentInteractionGraph
            agentTypes={nodeTypes}
            links={linkList}
            manifest={DEFAULT_AGENT_MANIFEST_V1}
            onEdgeSelect={(a, b) => {
              s.setLastAgentPair({ a, b });
              const params: string = new URLSearchParams({ a, b }).toString();
              nav(`/team?${params}`);
            }}
          />
        </div>
      </section>
    </div>
  );
}
