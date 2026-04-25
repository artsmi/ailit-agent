import React from "react";
import { mockWorkspace } from "../state/mockData";

export function ProjectsPage(): React.JSX.Element {
  return (
    <section className="card">
      <div className="cardHeader">Проекты (registry, mock)</div>
      <div className="cardBody">
        {mockWorkspace.projects.map((p) => (
          <div key={p.projectId} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
              <div style={{ fontWeight: 850 }}>{p.title}</div>
              <span className="pill" style={{ background: p.active ? "rgba(224, 64, 160, 0.14)" : "transparent" }}>
                <span style={{ fontWeight: 800 }}>{p.active ? "active" : "inactive"}</span>
              </span>
            </div>
            <div className="mono">{p.namespace}</div>
            <div className="mono">{p.path}</div>
          </div>
        ))}
        <div className="mono">
          В runtime версии сюда придёт `ailit project add` + локальный `.ailit/config.yaml` (это будет G9.3).
        </div>
      </div>
    </section>
  );
}

