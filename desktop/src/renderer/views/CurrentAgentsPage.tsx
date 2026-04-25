import React from "react";
import { Link } from "react-router-dom";

import { agentTypeFromRef, DEFAULT_AGENT_MANIFEST_V1, getManifestEntry } from "../state/agentManifest";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

/**
 * Список типов агентов: manifest (включ. AgentDummy) + типы из live trace, без if по роуту.
 */
function uniqueAgentTypesFromContext(
  liveTypes: ReadonlySet<string>
): readonly string[] {
  const mTypes: string[] = DEFAULT_AGENT_MANIFEST_V1.entries.map((e) => e.agentType);
  const merged: Set<string> = new Set([...mTypes, ...liveTypes]);
  return [...merged].sort();
}

function connHint(conn: string): { label: string; tone: "ok" | "warn" | "bad" } {
  if (conn === "ready") {
    return { label: "готов (broker/trace)", tone: "ok" };
  }
  if (conn === "connecting") {
    return { label: "подключаемся", tone: "warn" };
  }
  if (conn === "error") {
    return { label: "ошибка соединения", tone: "bad" };
  }
  return { label: conn, tone: "warn" };
}

export function CurrentAgentsPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const fromTrace: Set<string> = new Set();
  for (const r of s.rawTraceRows) {
    for (const k of ["from_agent", "to_agent"] as const) {
      const ref: string = String((r as Record<string, unknown>)[k] ?? "");
      if (ref) {
        const t: string = agentTypeFromRef(ref);
        if (t.startsWith("Agent")) {
          fromTrace.add(t);
        }
      }
    }
  }
  const liveTypes: ReadonlySet<string> = fromTrace;
  const useLive: boolean = s.rawTraceRows.length > 0;
  const agents: readonly string[] = useLive ? uniqueAgentTypesFromContext(liveTypes) : mockWorkspace.agents.map((a) => a.agentType);
  const links = useLive ? s.agentLinkKeys : mockWorkspace.agentLinks.map((l) => ({ fromType: l.fromAgentType, toType: l.toAgentType }));
  const ch: { label: string; tone: "ok" | "warn" | "bad" } = connHint(s.connection);
  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Агенты (manifest + trace)</div>
        <div className="cardBody">
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }} className="mono">
            <span className="pill">сессия: {s.connection}</span>
            <span
              className="pill"
              style={{
                borderColor:
                  ch.tone === "ok" ? "var(--candy-accent-2)" : ch.tone === "bad" ? "#c62828" : undefined
              }}
            >
              {ch.label}
            </span>
          </div>
          {agents.map((t) => {
            const a = getManifestEntry(DEFAULT_AGENT_MANIFEST_V1, t);
            return (
              <div
                key={t}
                style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "center" }}
                aria-label={a.displayName}
              >
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 999,
                    background: a.color,
                    boxShadow: `0 0 0 6px ${a.color}22`
                  }}
                />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 800 }}>{a.displayName}</div>
                  <div className="mono">{a.agentType}</div>
                  <div style={{ color: "var(--candy-text-2)" }}>{a.role}</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Связи (из trace, клик → диалог пары)</div>
        <div className="cardBody">
          {links.map((l) => (
            <div key={`${l.fromType}->${l.toType}`} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 750, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <span>
                  {l.fromType} → {l.toType}
                </span>
                <Link
                  to={`/agent-dialogue?a=${encodeURIComponent(l.fromType)}&b=${encodeURIComponent(l.toType)}`}
                  className="pill"
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  открыть диалог
                </Link>
              </div>
            </div>
          ))}
          {useLive ? null : <div className="mono" style={{ marginTop: 8 }}>сейчас мок. При live связи строятся по trace rows.</div>}
        </div>
      </section>
    </div>
  );
}
