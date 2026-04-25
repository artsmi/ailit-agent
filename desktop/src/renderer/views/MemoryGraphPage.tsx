import React from "react";
import { mockWorkspace } from "../state/mockData";

type HighlightState = {
  readonly kind: "pag.search.highlight";
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly ttlMs: number;
  readonly startedAtMs: number;
};

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

export function MemoryGraphPage(): React.JSX.Element {
  const [highlight, setHighlight] = React.useState<HighlightState | null>(null);
  const [, forceTick] = React.useState<number>(0);

  React.useEffect(() => {
    const id: number = window.setInterval(() => forceTick((x) => x + 1), 100);
    return () => window.clearInterval(id);
  }, []);

  const atMs: number = nowMs();
  const alive: boolean = highlight !== null && isAlive(highlight, atMs);
  const glow: number = highlight !== null && alive ? intensity01(highlight, atMs) : 0;

  function triggerMockSearchHighlight(): void {
    setHighlight({
      kind: "pag.search.highlight",
      nodeIds: ["B:tools/ailit/cli.py", "B:tools/agent_core/runtime/broker.py"],
      edgeIds: ["e1", "e2"],
      ttlMs: 3000,
      startedAtMs: nowMs()
    });
  }

  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Memory Graph (PAG only, mock)</div>
        <div className="cardBody">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div className="pill">
              <span>highlight decay</span>
              <span className="mono">ttl≈3s</span>
            </div>
            <button className="primaryButton" type="button" onClick={triggerMockSearchHighlight}>
              Trigger search highlight
            </button>
          </div>
          <div style={{ marginTop: 16 }}>
            {mockWorkspace.pag.nodes.map((n) => {
              const isHot: boolean = alive && highlight !== null && highlight.nodeIds.includes(n.id);
              const shadow: string = isHot ? `0 0 0 ${3 + glow * 8}px rgba(224, 64, 160, ${0.1 + glow * 0.35})` : "";
              return (
                <div
                  key={n.id}
                  style={{
                    marginBottom: 10,
                    padding: "10px 12px",
                    borderRadius: 14,
                    border: "1px solid var(--candy-border)",
                    background: "rgba(255,255,255,0.7)",
                    boxShadow: shadow,
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 750 }}>{n.label}</div>
                    <div className="mono">{n.id}</div>
                  </div>
                  <div className="pill" style={{ background: "transparent" }}>
                    <span>{n.level}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Edges (mock)</div>
        <div className="cardBody">
          {mockWorkspace.pag.edges.map((e) => {
            const isHot: boolean = alive && highlight !== null && highlight.edgeIds.includes(e.id);
            const opacity: number = isHot ? 0.35 + glow * 0.5 : 0.12;
            return (
              <div
                key={e.id}
                style={{
                  marginBottom: 10,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: "1px solid var(--candy-border)",
                  background: `rgba(224, 64, 160, ${opacity})`
                }}
              >
                <div style={{ fontWeight: 750 }}>
                  {e.from} → {e.to}
                </div>
                <div className="mono">{e.id}</div>
              </div>
            );
          })}
          <div className="mono">Это упрощённый mock: рёбра и узлы показываются списком, но highlight-поведение каноническое (ttl + decay).</div>
        </div>
      </section>
    </div>
  );
}

