import { mockWorkspace } from "./mockData";

export type MockSessionReportV1 = {
  readonly kind: "ailit_desktop_session_report_v1";
  readonly generatedAtIso: string;
  readonly projects: readonly {
    readonly projectId: string;
    readonly namespace: string;
    readonly path: string;
    readonly title: string;
  }[];
  readonly chat: readonly {
    readonly from: "user" | "assistant";
    readonly text: string;
    readonly atIso: string;
  }[];
  readonly agentDialogue: readonly {
    readonly fromAgent: string;
    readonly toAgent: string;
    readonly humanText: string;
    readonly technicalSummary: string;
    readonly severity: "info" | "warning" | "error";
    readonly atIso: string;
  }[];
  readonly pag: {
    readonly nodes: readonly { readonly id: string; readonly label: string; readonly level: "A" | "B" | "C" }[];
    readonly edges: readonly { readonly id: string; readonly from: string; readonly to: string }[];
  };
  readonly toolLogs: readonly string[];
  readonly usage: {
    readonly tokensIn: number;
    readonly tokensOut: number;
    readonly costUsd: number;
  };
  readonly runtimeHealth: {
    readonly mode: "mock";
    readonly supervisor: "unknown";
    readonly broker: "unknown";
  };
};

function nowIso(): string {
  return new Date().toISOString();
}

export function buildMockSessionReportV1(): MockSessionReportV1 {
  return {
    kind: "ailit_desktop_session_report_v1",
    generatedAtIso: nowIso(),
    projects: mockWorkspace.projects.map((p) => ({
      projectId: p.projectId,
      namespace: p.namespace,
      path: p.path,
      title: p.title
    })),
    chat: mockWorkspace.chat.map((m) => ({ from: m.from, text: m.text, atIso: m.atIso })),
    agentDialogue: mockWorkspace.agentDialogue.map((d) => ({
      fromAgent: d.fromAgent,
      toAgent: d.toAgent,
      humanText: d.humanText,
      technicalSummary: d.technicalSummary,
      severity: d.severity,
      atIso: d.atIso
    })),
    pag: {
      nodes: mockWorkspace.pag.nodes.map((n) => ({ id: n.id, label: n.label, level: n.level })),
      edges: mockWorkspace.pag.edges.map((e) => ({ id: e.id, from: e.from, to: e.to }))
    },
    toolLogs: mockWorkspace.toolLogs,
    usage: mockWorkspace.usage,
    runtimeHealth: {
      mode: "mock",
      supervisor: "unknown",
      broker: "unknown"
    }
  };
}

export function reportToMarkdown(report: MockSessionReportV1): string {
  const lines: string[] = [];
  lines.push(`# ailit desktop report`);
  lines.push(``);
  lines.push(`- generated_at: ${report.generatedAtIso}`);
  lines.push(`- mode: ${report.runtimeHealth.mode}`);
  lines.push(``);
  lines.push(`## Projects`);
  for (const p of report.projects) {
    lines.push(`- **${p.title}** \`${p.namespace}\``);
    lines.push(`  - id: \`${p.projectId}\``);
    lines.push(`  - path: \`${p.path}\``);
  }
  lines.push(``);
  lines.push(`## Chat transcript`);
  for (const m of report.chat) {
    const who: string = m.from === "user" ? "User" : "Assistant";
    lines.push(`- **${who}** (${m.atIso})`);
    lines.push(`  - ${m.text}`);
  }
  lines.push(``);
  lines.push(`## Agent dialogue`);
  for (const d of report.agentDialogue) {
    lines.push(`- **${d.fromAgent} → ${d.toAgent}** (${d.atIso})`);
    lines.push(`  - ${d.humanText}`);
    lines.push(`  - _${d.technicalSummary}_`);
  }
  lines.push(``);
  lines.push(`## Usage`);
  lines.push(`- tokens_in: ${report.usage.tokensIn}`);
  lines.push(`- tokens_out: ${report.usage.tokensOut}`);
  lines.push(`- cost_usd: ${report.usage.costUsd}`);
  lines.push(``);
  lines.push(`## Tool logs`);
  for (const row of report.toolLogs) {
    lines.push(`- ${row}`);
  }
  lines.push(``);
  return lines.join("\n");
}

function downloadTextFile(params: { readonly filename: string; readonly content: string; readonly mime: string }): void {
  const blob: Blob = new Blob([params.content], { type: params.mime });
  const url: string = URL.createObjectURL(blob);
  const a: HTMLAnchorElement = document.createElement("a");
  a.href = url;
  a.download = params.filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadReportJson(report: MockSessionReportV1): void {
  downloadTextFile({
    filename: "ailit-session-report.mock.json",
    content: JSON.stringify(report, null, 2),
    mime: "application/json"
  });
}

export function downloadReportMarkdown(report: MockSessionReportV1): void {
  downloadTextFile({
    filename: "ailit-session-report.mock.md",
    content: reportToMarkdown(report),
    mime: "text/markdown"
  });
}

