import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function WorkspaceBadge(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const titles: string = s.registry
    .filter((p) => s.selectedProjectIds.includes(p.projectId))
    .map((p) => p.title)
    .join(" + ");
  return (
    <div className="pill" aria-label="Активные проекты">
      <span>workspace</span>
      <span className="mono" style={{ maxWidth: 400, textOverflow: "ellipsis", overflow: "hidden" }}>
        {titles || "—"}
      </span>
    </div>
  );
}
