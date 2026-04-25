import type { AgentDialogueMessage } from "../runtime/agentDialogueProjection";
import type { NormalizedTraceProjection } from "../runtime/traceNormalize";
import { mockWorkspace } from "./mockData";

/** Единый отчёт G9.6: mock или live, JSON schema `ailit_desktop_session_report_v1`. */
export type AilitDesktopSessionReportV1 = {
  readonly kind: "ailit_desktop_session_report_v1";
  readonly generatedAtIso: string;
  readonly projects: readonly {
    readonly projectId: string;
    readonly namespace: string;
    readonly path: string;
    readonly title: string;
  }[];
  readonly chat: readonly {
    readonly from: "user" | "assistant" | "system";
    readonly text: string;
    readonly atIso: string;
  }[];
  readonly agentDialogue: readonly {
    readonly messageId: string;
    readonly label: string;
    readonly text: string;
    readonly technical: string;
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
  readonly rawTraceMessageIds: readonly string[];
  readonly runtimeHealth: {
    readonly mode: "mock" | "live";
    readonly connection: string;
    readonly runtimeDir: string | null;
    readonly brokerEndpoint: string | null;
    readonly lastError: string | null;
  };
};

function nowIso(): string {
  return new Date().toISOString();
}

export function buildMockSessionReportV1(): AilitDesktopSessionReportV1 {
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
      messageId: d.id,
      label: `${d.fromAgent} → ${d.toAgent}`,
      text: d.humanText,
      technical: d.technicalSummary,
      atIso: d.atIso
    })),
    pag: {
      nodes: mockWorkspace.pag.nodes.map((n) => ({ id: n.id, label: n.label, level: n.level })),
      edges: mockWorkspace.pag.edges.map((e) => ({ id: e.id, from: e.from, to: e.to }))
    },
    toolLogs: mockWorkspace.toolLogs,
    usage: mockWorkspace.usage,
    rawTraceMessageIds: [],
    runtimeHealth: {
      mode: "mock",
      connection: "mock",
      runtimeDir: null,
      brokerEndpoint: null,
      lastError: null
    }
  };
}

export function buildLiveSessionReportV1(params: {
  readonly projects: AilitDesktopSessionReportV1["projects"];
  readonly chat: AilitDesktopSessionReportV1["chat"];
  readonly agentDialogueMessages: readonly AgentDialogueMessage[] | null;
  readonly normalizedRows: readonly NormalizedTraceProjection[];
  readonly rawTraceRows: readonly Record<string, unknown>[];
  readonly toolLogs: readonly string[];
  readonly connection: string;
  readonly runtimeDir: string | null;
  readonly brokerEndpoint: string | null;
  readonly lastError: string | null;
}): AilitDesktopSessionReportV1 {
  const mids: string[] = [];
  for (const r of params.rawTraceRows) {
    const m: unknown = r["message_id"];
    if (typeof m === "string" && m) {
      mids.push(m);
    }
  }
  return {
    kind: "ailit_desktop_session_report_v1",
    generatedAtIso: nowIso(),
    projects: params.projects,
    chat: params.chat,
    agentDialogue:
      params.agentDialogueMessages && params.agentDialogueMessages.length > 0
        ? params.agentDialogueMessages.map((d) => ({
            messageId: d.rawRef.messageId,
            label: `${d.fromDisplay} → ${d.toDisplay}`,
            text: d.humanText,
            technical: d.technicalSummary,
            atIso: d.createdAt
          }))
        : params.normalizedRows.map((n) => ({
            messageId: n.messageId,
            label: n.kind,
            text: n.humanLine,
            technical: n.technicalLine,
            atIso: n.createdAt
          })),
    pag: { nodes: [], edges: [] },
    toolLogs: params.toolLogs,
    usage: { tokensIn: 0, tokensOut: 0, costUsd: 0 },
    rawTraceMessageIds: mids,
    runtimeHealth: {
      mode: "live",
      connection: params.connection,
      runtimeDir: params.runtimeDir,
      brokerEndpoint: params.brokerEndpoint,
      lastError: params.lastError
    }
  };
}

export function reportToMarkdown(report: AilitDesktopSessionReportV1): string {
  const lines: string[] = [];
  lines.push(`# ailit desktop report`);
  lines.push(``);
  lines.push(`- generated_at: ${report.generatedAtIso}`);
  lines.push(
    `- mode: ${report.runtimeHealth.mode} (connection=${report.runtimeHealth.connection})`
  );
  if (report.runtimeHealth.runtimeDir) {
    lines.push(`- runtime_dir: \`${report.runtimeHealth.runtimeDir}\``);
  }
  if (report.runtimeHealth.brokerEndpoint) {
    lines.push(`- broker: \`${report.runtimeHealth.brokerEndpoint}\``);
  }
  if (report.runtimeHealth.lastError) {
    lines.push(`- last_error: ${report.runtimeHealth.lastError}`);
  }
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
    const who: string = m.from === "user" ? "User" : m.from === "system" ? "System" : "Assistant";
    lines.push(`- **${who}** (${m.atIso})`);
    lines.push(`  - ${m.text}`);
  }
  lines.push(``);
  lines.push(`## Agent dialogue (from trace / mock)`);
  for (const d of report.agentDialogue) {
    lines.push(`- **${d.label}** [${d.messageId}] (${d.atIso})`);
    lines.push(`  - ${d.text}`);
    lines.push(`  - _${d.technical}_`);
  }
  lines.push(``);
  lines.push(`## Raw trace message ids`);
  for (const id of report.rawTraceMessageIds.slice(0, 500)) {
    lines.push(`- \`${id}\``);
  }
  if (report.rawTraceMessageIds.length > 500) {
    lines.push(`- … ${report.rawTraceMessageIds.length - 500} more`);
  }
  lines.push(``);
  lines.push(`## Usage`);
  lines.push(`- tokens_in: ${report.usage.tokensIn}`);
  lines.push(`- tokens_out: ${report.usage.tokensOut}`);
  lines.push(`- cost_usd: ${report.usage.costUsd}`);
  lines.push(``);
  lines.push(`## Tool logs / trace summary`);
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

export async function saveReportJsonViaBridge(report: AilitDesktopSessionReportV1): Promise<void> {
  if (window.ailitDesktop?.saveTextFile) {
    const r: Awaited<ReturnType<NonNullable<typeof window.ailitDesktop.saveTextFile>>> = await window.ailitDesktop.saveTextFile({
      suggestedName: "ailit-session-report.json",
      content: JSON.stringify(report, null, 2)
    });
    if (r.ok) {
      return;
    }
  }
  downloadTextFile({
    filename: "ailit-session-report.json",
    content: JSON.stringify(report, null, 2),
    mime: "application/json"
  });
}

export async function saveReportMarkdownViaBridge(report: AilitDesktopSessionReportV1): Promise<void> {
  if (window.ailitDesktop?.saveTextFile) {
    const r: Awaited<ReturnType<NonNullable<typeof window.ailitDesktop.saveTextFile>>> = await window.ailitDesktop.saveTextFile({
      suggestedName: "ailit-session-report.md",
      content: reportToMarkdown(report)
    });
    if (r.ok) {
      return;
    }
  }
  downloadTextFile({
    filename: "ailit-session-report.md",
    content: reportToMarkdown(report),
    mime: "text/markdown"
  });
}
