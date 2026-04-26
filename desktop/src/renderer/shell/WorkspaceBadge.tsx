import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function WorkspaceBadge(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const titles: string = s.registry
    .filter((p) => s.selectedProjectIds.includes(p.projectId))
    .map((p) => p.title)
    .join(" + ");
  return (
    <div className="pill smPill" aria-label="projects">
      <span className="enTok">workspace</span>
      <span className="wbText" title={titles || undefined}>
        {titles || "—"}
      </span>
    </div>
  );
}
