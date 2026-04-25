import React from "react";
import { mockWorkspace } from "../state/mockData";

export function MockWorkspaceBadge(): React.JSX.Element {
  const activeProjects: string = mockWorkspace.projects
    .filter((p) => p.active)
    .map((p) => p.title)
    .join(" + ");

  return (
    <div className="pill" aria-label="Активные проекты">
      <span>workspace</span>
      <span className="mono">{activeProjects}</span>
    </div>
  );
}

