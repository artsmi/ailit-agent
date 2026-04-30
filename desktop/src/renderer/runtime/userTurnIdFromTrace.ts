function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function strField(row: Record<string, unknown>, key: string): string {
  const v: unknown = row[key];
  return typeof v === "string" ? v : v === null || v === undefined ? "" : String(v);
}

/**
 * Последний `user_turn_id` из исходящего `memory.query_context` (AgentWork → AgentMemory)
 * для корреляции cooperative cancel (plan.md §волна 4).
 */
export class BrokerTraceUserTurnResolver {
  public static latestForChat(rows: readonly Record<string, unknown>[], chatId: string): string {
    if (!chatId) {
      return "";
    }
    for (let i: number = rows.length - 1; i >= 0; i -= 1) {
      const row: Record<string, unknown> = rows[i] as Record<string, unknown>;
      if (strField(row, "chat_id") !== chatId) {
        continue;
      }
      if (strField(row, "type") !== "service.request") {
        continue;
      }
      if (strField(row, "from_agent") !== `AgentWork:${chatId}`) {
        continue;
      }
      const to: string = strField(row, "to_agent");
      if (!to.startsWith("AgentMemory:")) {
        continue;
      }
      const pl: Record<string, unknown> | null = asDict(row["payload"]);
      if (!pl || String(pl["service"] ?? "") !== "memory.query_context") {
        continue;
      }
      const ut: unknown = pl["user_turn_id"];
      if (typeof ut === "string" && ut.trim().length > 0) {
        return ut.trim();
      }
    }
    return "";
  }
}
