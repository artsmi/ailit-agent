import React from "react";

import { projectMemoryJournalRows, type MemoryJournalDisplayRow } from "../../runtime/memoryJournalProjection";
import { useDesktopSession } from "../../runtime/DesktopSessionContext";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

function shortTime(iso: string): string {
  if (!iso) {
    return "--:--:--";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleTimeString();
}

export function MemoryJournalPanel({
  chatId
}: {
  readonly chatId: string;
}): React.JSX.Element {
  const { desktopConfig } = useDesktopSession();
  const pollMs: number = desktopConfig?.memory_journal_poll_ms ?? 2000;
  const [rows, setRows] = React.useState<readonly MemoryJournalDisplayRow[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const [path, setPath] = React.useState<string>("");

  const load = React.useCallback(async (): Promise<void> => {
    const res = await window.ailitDesktop.memoryJournalRead({ chatId, limit: 400 });
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    setErr(null);
    setPath(res.path);
    setRows(projectMemoryJournalRows(res.rows, chatId));
  }, [chatId]);

  React.useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      void load();
    }, pollMs);
    return () => window.clearInterval(id);
  }, [load, pollMs]);

  return (
    <section className="memoryJournalPanel">
      <div className="memoryJournalPanelHead">
        <div>
          <div className="fontW800">AgentMemory journal</div>
          <div className="memoryJournalPath">{path || "~/.ailit/runtime/memory-journal.jsonl"}</div>
        </div>
        <button className="pill" type="button" onClick={() => void load()}>
          refresh
        </button>
      </div>
      {err ? <div className="errLine">{err}</div> : null}
      {rows.length === 0 ? (
        <div className="memoryJournalEmpty">
          <CandyMaterialIcon name="receipt_long" />
          <span>Для активного chat_id пока нет записей журнала.</span>
        </div>
      ) : (
        <div className="memoryJournalRows">
          {rows.map((row) => (
            <article className={row.partial ? "memoryJournalRow memoryJournalRowPartial" : "memoryJournalRow"} key={row.id}>
              <div className="memoryJournalRowTop">
                <span>{shortTime(row.createdAt)}</span>
                <span>{row.eventName}</span>
              </div>
              <div className="memoryJournalSummary">{row.summary || "—"}</div>
              <div className="memoryJournalMeta">
                <span>chat: {row.chatId}</span>
                {row.namespace ? <span>ns: {row.namespace}</span> : null}
                {row.nextAction ? <span>next: {row.nextAction}</span> : null}
              </div>
              {row.nodeIds.length > 0 ? (
                <div className="memoryJournalChips">
                  {row.nodeIds.slice(0, 6).map((id) => (
                    <span className="contextFillChip" key={id}>{id}</span>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
