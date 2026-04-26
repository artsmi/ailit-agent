import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

type CandyChatAgentStatusRowProps = {
  readonly active: boolean;
};

/**
 * Полоса «агент в работе» (реф.: candy, shimmer, компактно над полем ввода).
 */
export function CandyChatAgentStatusRow({ active }: CandyChatAgentStatusRowProps): React.JSX.Element | null {
  if (!active) {
    return null;
  }
  return (
    <div className="candyChatAgentStatus" aria-live="polite" role="status">
      <div className="candyChatAgentStatusShimmer" aria-hidden="true" />
      <div className="candyChatAgentStatusInner">
        <span className="candyChatAgentStatusIcon" aria-hidden="true">
          <CandyMaterialIcon name="psychology" />
        </span>
        <span className="candyChatAgentStatusText">Ailit думает</span>
        <span className="candyChatAgentStatusDots" aria-hidden="true">
          <span className="candyChatAgentDot" />
          <span className="candyChatAgentDot" />
          <span className="candyChatAgentDot" />
        </span>
      </div>
    </div>
  );
}
