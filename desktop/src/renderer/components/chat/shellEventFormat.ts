/**
 * Читаемая проекция bash/tool событий из topic.publish (без сырого JSON в чате).
 */

/**
 * Внутренний payload события topic.publish: payload.payload.
 */
export function extractToolEventInner(raw: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const top = raw["payload"];
  if (top == null || typeof top !== "object" || Array.isArray(top)) {
    return {};
  }
  const pl = top as Record<string, unknown>;
  if (pl["type"] === "topic.publish" && pl["payload"] != null && typeof pl["payload"] === "object" && !Array.isArray(pl["payload"])) {
    return pl["payload"] as Record<string, unknown>;
  }
  return {};
}

/**
 * Снимает питоновский b'...' / лишние кавычки в stdout из chunk.
 */
export function normalizeBashOutputChunk(s: string): string {
  const t: string = s.trim();
  if (t.length === 0) {
    return "";
  }
  if (t.startsWith("b'") && t.length > 2) {
    const unquote: string = t.slice(2);
    if (unquote.endsWith("'")) {
      return unquote.slice(0, -1).replace(/\\n/g, "\n").replace(/\\'/g, "'") + (s.endsWith("\n") ? "\n" : "");
    }
  }
  if (t.startsWith("b\"") && t.length > 2) {
    const u: string = t.slice(2);
    if (u.endsWith("\"")) {
      return u.slice(0, -1).replace(/\\n/g, "\n") + (s.endsWith("\n") ? "\n" : "");
    }
  }
  return s;
}

/**
 * true — события bash.*, объединяем в один блок по call_id.
 */
export function isBashEventName(humanEventName: string): boolean {
  return /^bash\./i.test(humanEventName.trim());
}

/**
 * Сводка длину для не-bash tool.* без длинного JSON.
 */
export function shortToolLine(eventName: string, inner: Readonly<Record<string, unknown>>): string {
  if (Object.keys(inner).length === 0) {
    return eventName;
  }
  if (eventName === "tool.run" && typeof inner["name"] === "string") {
    return `${eventName} — ${inner["name"] as string}`;
  }
  if (eventName === "tool.result" && typeof inner["ok"] === "boolean") {
    return `${eventName} — ${(inner["ok"] as boolean) ? "ok" : "error"}`;
  }
  return eventName;
}

export function buildBashLineDelta(
  eventName: string,
  inner: Readonly<Record<string, unknown>>,
  accBefore: string
): { readonly next: string; readonly didChange: boolean } {
  if (eventName === "bash.execution") {
    const rawCmd: string = String(inner["command"] ?? "").trim() || "…";
    if (accBefore.includes(`▸ ${rawCmd}`) || /^▸\s/m.test(accBefore)) {
      return { next: accBefore, didChange: false };
    }
    return { next: `▸ ${rawCmd}\n\n${accBefore}`, didChange: true };
  }
  if (eventName === "bash.output_delta") {
    const chunk: string = inner["chunk"] == null ? "" : normalizeBashOutputChunk(String(inner["chunk"]));
    if (chunk.length === 0) {
      return { next: accBefore, didChange: false };
    }
    return { next: accBefore + chunk, didChange: true };
  }
  if (eventName === "bash.finished" || /bash\.(end|close)/i.test(eventName)) {
    const ok: boolean = inner["ok"] === true;
    if (ok && /(^|\n)—\nГотово\s*$/.test(accBefore)) {
      return { next: accBefore, didChange: false };
    }
    if (ok) {
      return { next: accBefore + "\n\n—\nГотово", didChange: true };
    }
    return { next: accBefore + "\n\n—\nОшибка: " + String(inner["error"] ?? "—"), didChange: true };
  }
  if (isBashEventName(eventName)) {
    if (Object.keys(inner).length === 0) {
      return { next: accBefore, didChange: false };
    }
    return { next: accBefore, didChange: false };
  }
  return { next: accBefore, didChange: false };
}

export function callIdForBashEvent(inner: Readonly<Record<string, unknown>>, messageId: string): string {
  const c: unknown = inner["call_id"];
  if (typeof c === "string" && c.length > 0) {
    return c;
  }
  return `msg-${messageId}`;
}
