import React from "react";

import type { BrokerMemoryRecallUiPhase } from "../../runtime/memoryRecallUiPhaseProjection";
import { recallPhraseTextAtIndex } from "../../runtime/memoryRecallUiPhaseProjection";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

type CandyChatMemoryRecallStatusRowProps = {
  readonly phase: BrokerMemoryRecallUiPhase;
};

export function CandyChatMemoryRecallStatusRow({
  phase
}: CandyChatMemoryRecallStatusRowProps): React.JSX.Element | null {
  if (!phase.active) {
    return null;
  }
  const label: string = recallPhraseTextAtIndex(phase.phraseIndex);
  return (
    <div
      className="candyChatMemoryRecallStatus"
      aria-live="polite"
      role="status"
      data-style-token={phase.styleToken}
    >
      <div className="candyChatMemoryRecallStatusShimmer" aria-hidden="true" />
      <div className="candyChatMemoryRecallStatusInner">
        <span className="candyChatMemoryRecallStatusIcon" aria-hidden="true">
          <CandyMaterialIcon name="psychology" />
        </span>
        <span className="candyChatMemoryRecallStatusText">{label}</span>
        <span className="candyChatMemoryRecallStatusDots" aria-hidden="true">
          <span className="candyChatMemoryRecallDot" />
          <span className="candyChatMemoryRecallDot" />
          <span className="candyChatMemoryRecallDot" />
        </span>
      </div>
    </div>
  );
}
