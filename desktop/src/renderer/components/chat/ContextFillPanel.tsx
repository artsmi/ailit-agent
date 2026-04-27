import React from "react";

import type { ContextFillState } from "../../runtime/chatTraceProjector";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

const BREAKDOWN_LABELS: Readonly<Record<string, string>> = {
  system: "system",
  tools: "tools",
  messages: "messages",
  memory_abc: "memory A/B/C",
  memory_d: "memory D",
  tool_results: "tool results",
  free: "free"
};

function formatTokens(v: number): string {
  if (v >= 1_000_000) {
    return `${(v / 1_000_000).toFixed(1)}M`;
  }
  if (v >= 1000) {
    return `${(v / 1000).toFixed(1)}k`;
  }
  return String(Math.round(v));
}

function stateLabel(s: ContextFillState["warningState"]): string {
  if (s === "overflow_risk") {
    return "overflow risk";
  }
  if (s === "compact_recommended") {
    return "compact recommended";
  }
  if (s === "warning") {
    return "warning";
  }
  return "normal";
}

export function ContextFillPanel({
  state
}: {
  readonly state: ContextFillState | null;
}): React.JSX.Element | null {
  if (state === null) {
    return null;
  }
  const pct: number = Math.max(0, Math.min(100, state.contextUsagePercent));
  const used: number =
    state.usageState === "confirmed" && state.confirmedContextTokens !== null
      ? state.confirmedContextTokens
      : state.estimatedContextTokens;
  const breakdownEntries: readonly [string, number][] = Object.entries(state.breakdown)
    .filter(([, v]) => v > 0)
    .sort((a, b) => {
      if (a[0] === "free") {
        return 1;
      }
      if (b[0] === "free") {
        return -1;
      }
      return b[1] - a[1];
    });
  return (
    <section className={`contextFillPanel contextFillPanel-${state.warningState}`} aria-label="LLM context fill">
      <div className="contextFillTop">
        <div className="contextFillTitle">
          <CandyMaterialIcon name="data_usage" />
          <span>Context</span>
          <span className="contextFillMode">{state.usageState}</span>
        </div>
        <div className="contextFillPct">{state.contextUsagePercent.toFixed(1)}%</div>
      </div>
      <div className="contextFillBar" aria-hidden="true">
        <div className="contextFillBarInner" style={{ width: `${pct}%` }} />
      </div>
      <div className="contextFillMeta">
        <span>
          {formatTokens(used)} / {formatTokens(state.effectiveContextLimit)}
        </span>
        <span>{state.model || "model"}</span>
        <span>{stateLabel(state.warningState)}</span>
      </div>
      <div className="contextFillBreakdown">
        {breakdownEntries.slice(0, 7).map(([k, v]) => (
          <span className={`contextFillChip contextFillChip-${k}`} key={k}>
            {BREAKDOWN_LABELS[k] ?? k}: {formatTokens(v)}
          </span>
        ))}
      </div>
    </section>
  );
}
