import React from "react";

import type { BrokerAgentThinkingUiPhase } from "../../runtime/memoryRecallUiPhaseProjection";
import { thinkingPhraseTextAtIndex } from "../../runtime/memoryRecallUiPhaseProjection";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

type CandyChatAgentStatusRowProps = {
  readonly phase: BrokerAgentThinkingUiPhase;
};

/**
 * Полоса «агент в работе» (реф.: candy, shimmer, компактно над полем ввода).
 */
export function CandyChatAgentStatusRow({ phase }: CandyChatAgentStatusRowProps): React.JSX.Element | null {
  if (!phase.active) {
    return null;
  }
  const label: string = thinkingPhraseTextAtIndex(phase.phraseIndex);
  return (
    <div
      className="candyChatAgentStatus"
      aria-live="polite"
      role="status"
      data-style-token={phase.styleToken}
    >
      <div className="candyChatAgentStatusShimmer" aria-hidden="true" />
      <div className="candyChatAgentStatusInner">
        <span className="candyChatAgentStatusIcon" aria-hidden="true">
          <CandyMaterialIcon name="psychology" />
        </span>
        <span className="candyChatAgentStatusText">{label}</span>
        <span className="candyChatAgentStatusDots" aria-hidden="true">
          <span className="candyChatAgentDot" />
          <span className="candyChatAgentDot" />
          <span className="candyChatAgentDot" />
        </span>
      </div>
    </div>
  );
}
