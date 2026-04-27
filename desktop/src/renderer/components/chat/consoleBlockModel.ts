/**
 * Модель блока «консоль» в чате: разбор ailit-вывода run_shell (и plain-текста tool).
 */

const META_RE: RegExp = /^(exit_code|timed_out|cancelled|truncated|spill_path):/i;

const PREVIEW_TAIL_LINES: number = 3;

/**
 * Снимает лидирующий устаревший маркер `▸ `.
 */
function stripCommandMarker(line: string): string {
  return line.replace(/^\s*▸\s+/, "").trimEnd();
}

function isEmptyDisplayToken(line: string): boolean {
  return line.trim() === "(empty)";
}

export type ConsoleBlockStatus = "none" | "ok" | "error";

export class ParsedConsoleBlock {
  public readonly titleLine: string;
  public readonly contentLines: readonly string[];
  public readonly status: ConsoleBlockStatus;
  public readonly statusDetail: string | null;

  public constructor(
    titleLine: string,
    contentLines: readonly string[],
    status: ConsoleBlockStatus,
    statusDetail: string | null
  ) {
    this.titleLine = titleLine;
    this.contentLines = contentLines;
    this.status = status;
    this.statusDetail = statusDetail;
  }

  public get previewOutLines(): readonly string[] {
    if (this.contentLines.length === 0) {
      return [];
    }
    if (this.contentLines.length <= PREVIEW_TAIL_LINES) {
      return this.contentLines;
    }
    return this.contentLines.slice(-PREVIEW_TAIL_LINES);
  }

  public get hasExpandable(): boolean {
    return this.contentLines.length > PREVIEW_TAIL_LINES;
  }

  public get fullTextLines(): readonly string[] {
    return this.contentLines;
  }
}

/**
 * Удаляет «хвост» bash.finished из ailit-текста.
 */
function stripBashStatusFooter(
  text: string
): { readonly body: string; readonly status: ConsoleBlockStatus; readonly detail: string | null } {
  const t: string = text;
  const reErr: RegExp = /(?:\r\n|\n)\n—(?:\r\n|\n)Ошибка:\s*([\s\S]*?)\s*$/s;
  const mErr: RegExpMatchArray | null = t.match(reErr);
  if (mErr) {
    return { body: t.replace(reErr, ""), status: "error" as const, detail: mErr[1]!.trim() || "Ошибка" };
  }
  const reOk: RegExp = /(?:\r\n|\n)\n—(?:\r\n|\n)Готово\s*$/s;
  if (reOk.test(t)) {
    return { body: t.replace(reOk, ""), status: "ok" as const, detail: "Готово" };
  }
  return { body: t, status: "none" as const, detail: null };
}

/**
 * Собирает тело ailit из строк после команды: мета, stdout, stderr.
 * Строки после `--- stdout ---` / `--- stderr ---` оставляем **без** trim, кроме маркеров-разделителей.
 */
function tryParseAilitBody(
  afterCommandLines: readonly string[]
): { readonly isAilit: boolean; readonly out: readonly string[]; readonly err: readonly string[] } {
  if (afterCommandLines.length === 0) {
    return { isAilit: false, out: [], err: [] };
  }
  const withMarkers: boolean = afterCommandLines.some((L) => L.trim() === "--- stdout ---");
  if (!withMarkers) {
    return { isAilit: false, out: [], err: [] };
  }
  let i: number = 0;
  while (i < afterCommandLines.length && afterCommandLines[i]!.trim() === "") {
    i += 1;
  }
  while (i < afterCommandLines.length && META_RE.test(afterCommandLines[i]!.trimStart())) {
    i += 1;
  }
  while (i < afterCommandLines.length && afterCommandLines[i]!.trim() === "") {
    i += 1;
  }
  if (i >= afterCommandLines.length || afterCommandLines[i]!.trim() !== "--- stdout ---") {
    return { isAilit: true, out: [], err: [] };
  }
  i += 1;
  const outPart: string[] = [];
  for (; i < afterCommandLines.length; i += 1) {
    const rawL: string = afterCommandLines[i] as string;
    if (rawL.trim() === "--- stderr ---") {
      i += 1;
      break;
    }
    if (!isEmptyDisplayToken(rawL.trim())) {
      outPart.push(rawL);
    }
  }
  if (i >= afterCommandLines.length) {
    return { isAilit: true, out: outPart, err: [] };
  }
  const errPart: string[] = [];
  for (; i < afterCommandLines.length; i += 1) {
    const rawB: string = (afterCommandLines[i] as string) ?? "";
    if (!isEmptyDisplayToken(rawB.trim())) {
      errPart.push(rawB);
    }
  }
  return { isAilit: true, out: outPart, err: errPart };
}

function joinOutErr(out: readonly string[], err: readonly string[]): readonly string[] {
  if (out.length > 0 && err.length > 0) {
    return [...out, ...err];
  }
  if (out.length > 0) {
    return [...out];
  }
  if (err.length > 0) {
    return [...err];
  }
  return [];
}

/**
 * Разбирает сырое содержимое `CandyChatConsoleBlock` в заголовок и «чистые» строки.
 */
export function parseConsoleBlockText(raw: string): ParsedConsoleBlock {
  const stripped0: { readonly body: string; readonly status: ConsoleBlockStatus; readonly detail: string | null } = stripBashStatusFooter(
    raw.replace(/\r\n/g, "\n")
  );
  const allLines: string[] = stripped0.body.split("\n");
  if (allLines.length === 0) {
    return new ParsedConsoleBlock("…", [], stripped0.status, stripped0.detail);
  }
  const titleLine: string = ((): string => {
    const t: string = stripCommandMarker(allLines[0]!);
    return t.trim() === "" ? "…" : t;
  })();
  const afterFirst: string[] = allLines.length > 1 ? allLines.slice(1) : [];
  if (afterFirst.length === 0) {
    return new ParsedConsoleBlock(
      titleLine,
      [],
      stripped0.status,
      stripped0.status === "none" ? null : stripped0.detail
    );
  }
  const ailit: { readonly isAilit: boolean; readonly out: readonly string[]; readonly err: readonly string[] } = tryParseAilitBody(afterFirst);
  if (ailit.isAilit) {
    return new ParsedConsoleBlock(
      titleLine,
      [...joinOutErr(ailit.out, ailit.err)],
      stripped0.status,
      stripped0.status === "none" ? null : stripped0.detail
    );
  }
  return new ParsedConsoleBlock(
    titleLine,
    filterPlainToolBody(afterFirst),
    stripped0.status,
    stripped0.status === "none" ? null : stripped0.detail
  );
}

function filterPlainToolBody(after: readonly string[]): string[] {
  const out: string[] = [];
  let i: number = 0;
  while (i < after.length && (after[i] as string).trim() === "") {
    i += 1;
  }
  while (i < after.length && META_RE.test((after[i] as string).trimStart())) {
    i += 1;
  }
  for (; i < after.length; i += 1) {
    const L: string = (after[i] as string) ?? "";
    const tr: string = L.trim();
    if (tr === "—" || tr === "Готово") {
      continue;
    }
    if (isEmptyDisplayToken(L)) {
      continue;
    }
    out.push(L);
  }
  return out;
}
