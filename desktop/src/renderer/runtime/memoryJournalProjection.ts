export type MemoryJournalDisplayRow = {
  readonly id: string;
  readonly createdAt: string;
  readonly chatId: string;
  readonly eventName: string;
  readonly summary: string;
  readonly namespace: string;
  readonly projectId: string;
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly nextAction: string;
  readonly partial: boolean;
};

function str(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

function asDict(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function strList(v: unknown): readonly string[] {
  return Array.isArray(v) ? v.map((x) => str(x)).filter((x) => x.length > 0) : [];
}

export function projectMemoryJournalRows(
  rows: readonly Record<string, unknown>[],
  chatId: string
): readonly MemoryJournalDisplayRow[] {
  const out: MemoryJournalDisplayRow[] = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i]!;
    if (str(row["chat_id"]) !== chatId) {
      continue;
    }
    const payload = asDict(row["payload"]);
    out.push({
      id: `${str(row["created_at"]) || String(i)}:${str(row["event_name"])}`,
      createdAt: str(row["created_at"]),
      chatId: str(row["chat_id"]),
      eventName: str(row["event_name"]),
      summary: str(row["summary"]),
      namespace: str(row["namespace"]),
      projectId: str(row["project_id"]),
      nodeIds: strList(row["node_ids"]),
      edgeIds: strList(row["edge_ids"]),
      nextAction: str(payload["next_action"] ?? payload["recommended_next_step"]),
      partial: Boolean(payload["partial"])
    });
  }
  return out;
}
