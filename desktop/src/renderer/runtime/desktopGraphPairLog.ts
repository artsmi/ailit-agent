/**
 * Пара логов `ailit-desktop-full` / `ailit-desktop-compact`: UTC wall-clock,
 * source=AM (trace в renderer) и source=D (служебные события Desktop).
 */

function str(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
}

/** Системные часы, канон UTC ISO-8601 с Z (как toISOString). */
export function wallClockUtcIso(): string {
  return new Date().toISOString();
}

export function deriveTraceRowEventLabel(row: Readonly<Record<string, unknown>>): string {
  const t: string = str(row["type"]);
  if (t === "topic.publish") {
    const p: unknown = row["payload"];
    if (p && typeof p === "object" && !Array.isArray(p)) {
      const en: string = str((p as Record<string, unknown>)["event_name"]);
      if (en.length > 0) {
        return en;
      }
    }
  }
  if (t.length > 0) {
    return t;
  }
  return "unknown";
}

/** Полный блок: заголовок + одна строка JSON всей trace-row. */
export function buildAmFullLogBlock(
  tsUtc: string,
  traceSeq: number,
  row: Readonly<Record<string, unknown>>
): string {
  const ev: string = deriveTraceRowEventLabel(row);
  const header: string = `ts_utc=${tsUtc}\tsource=AM\ttrace_seq=${String(traceSeq)}\tevent=${ev}\n`;
  const body: string = JSON.stringify(row);
  return `${header}${body}\n`;
}

function escTab(s: string): string {
  return s.replace(/\t/g, " ");
}

/** Компактная строка для склейки с full по trace_seq. */
export function buildAmCompactLine(
  tsUtc: string,
  traceSeq: number,
  row: Readonly<Record<string, unknown>>
): string {
  const ev: string = deriveTraceRowEventLabel(row);
  const mid: string = escTab(str(row["message_id"]));
  const tid: string = escTab(str(row["trace_id"]));
  const ns: string = escTab(str(row["namespace"]));
  return (
    `ts_utc=${tsUtc}\tsource=AM\ttrace_seq=${String(traceSeq)}\tevent=${escTab(ev)}` +
    `\tmessage_id=${mid}\ttrace_id=${tid}\tnamespace=${ns}`
  );
}

/** Full: заголовок + JSON detail (весь объект). */
export function buildDFullLogBlock(
  tsUtc: string,
  desktopSeq: number,
  event: string,
  detail: Readonly<Record<string, unknown>>
): string {
  const header: string = `ts_utc=${tsUtc}\tsource=D\tdesktop_seq=${String(desktopSeq)}\tevent=${escTab(event)}\n`;
  const body: string = JSON.stringify(detail);
  return `${header}${body}\n`;
}

/** Компактная строка: event + однострочный JSON detail (без переводов строк). */
export function buildDCompactLine(
  tsUtc: string,
  desktopSeq: number,
  event: string,
  detail: Readonly<Record<string, unknown>>
): string {
  const jsonOne: string = JSON.stringify(detail).replace(/\r?\n/g, "\\n");
  const cap: number = 4000;
  const tail: string = jsonOne.length > cap ? `${jsonOne.slice(0, cap)}…` : jsonOne;
  return `ts_utc=${tsUtc}\tsource=D\tdesktop_seq=${String(desktopSeq)}\tevent=${escTab(event)}\tdetail=${tail}`;
}
