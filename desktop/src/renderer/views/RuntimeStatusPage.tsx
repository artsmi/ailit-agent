import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function RuntimeStatusPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Runtime status</div>
        <div className="cardBody">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="primaryButton" type="button" onClick={() => void s.refreshStatus()}>
              Refresh
            </button>
            <button type="button" onClick={() => void s.resubscribeTrace()}>
              Resubscribe trace
            </button>
          </div>
          <div style={{ height: 12 }} />
          <div className="pill">
            <span>подключение</span>
            <span className="mono">{s.connection}</span>
          </div>
          <div style={{ height: 8 }} />
          <div className="pill">
            <span>runtime_dir</span>
            <span className="mono">{s.runtimeDir ?? "—"}</span>
          </div>
          <div style={{ height: 8 }} />
          <div className="pill">
            <span>broker</span>
            <span className="mono" style={{ maxWidth: "100%" }}>
              {s.brokerEndpoint ?? "—"}
            </span>
          </div>
          <div style={{ height: 8 }} />
          {s.lastError && (
            <div className="mono" style={{ color: "var(--candy-warn, #a04010)" }}>
              {s.lastError}
            </div>
          )}
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Диагностика (service)</div>
        <div className="cardBody">
          <div className="mono" style={{ marginBottom: 10 }}>
            Если сокет supervisor-а не найден:
            <code style={{ display: "block", marginTop: 6 }}>systemctl --user status ailit.service</code>
            <code style={{ display: "block", marginTop: 4 }}>journalctl --user -u ailit.service -f</code>
          </div>
          <div className="mono" style={{ whiteSpace: "pre-wrap" }}>
            {s.supervisorSummary}
          </div>
        </div>
      </section>
    </div>
  );
}
