import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function ProjectsPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  return (
    <section className="card">
      <div className="cardHeader">Проекты (registry)</div>
      <div className="cardBody">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button className="primaryButton" type="button" onClick={() => void s.loadProjects()}>
            Refresh
          </button>
        </div>
        {s.registry.length ? (
          s.registry.map((p) => (
            <div key={p.projectId} style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div style={{ fontWeight: 850 }}>{p.title}</div>
                <span className="pill" style={{ background: s.selectedProjectIds.includes(p.projectId) ? "rgba(224, 64, 160, 0.14)" : "transparent" }}>
                  <span style={{ fontWeight: 800 }}>{s.selectedProjectIds.includes(p.projectId) ? "selected" : "off"}</span>
                </span>
              </div>
              <div className="mono">{p.namespace}</div>
              <div className="mono">{p.path}</div>
              <button className="mono" type="button" style={{ marginTop: 6, border: 0, background: "transparent", cursor: "pointer" }} onClick={() => s.toggleProject(p.projectId)}>
                {s.selectedProjectIds.includes(p.projectId) ? "убрать из чата" : "добавить в чат"}
              </button>
            </div>
          ))
        ) : (
          <div className="mono">Нет записей. Команда: ailit project add (или ailit project add PATH).</div>
        )}
      </div>
    </section>
  );
}
