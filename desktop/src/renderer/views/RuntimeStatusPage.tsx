import React from "react";

export function RuntimeStatusPage(): React.JSX.Element {
  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Runtime status (mock)</div>
        <div className="cardBody">
          <div className="pill">
            <span>supervisor</span>
            <span className="mono">unknown</span>
          </div>
          <div style={{ height: 10 }} />
          <div className="pill">
            <span>broker</span>
            <span className="mono">unknown</span>
          </div>
          <div style={{ height: 16 }} />
          <div className="mono">
            До G9.2 runtime integration запрещена. В runtime версии здесь будут подсказки:
            <div style={{ marginTop: 8 }} className="mono">
              - systemctl --user status ailit.service
              <br />- journalctl --user -u ailit.service -f
            </div>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Health / reconnect (placeholder)</div>
        <div className="cardBody">
          <div className="mono">
            Здесь будет reconnect state и диагностика unix-socket транспорта (G9.5). Сейчас — mock-only.
          </div>
        </div>
      </section>
    </div>
  );
}

