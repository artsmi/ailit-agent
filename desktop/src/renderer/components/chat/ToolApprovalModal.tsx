import React from "react";

/**
 * ASK на инструмент (session.waiting_approval) — стиль как PermMode (Candy).
 */
export function ToolApprovalModal(props: {
  readonly open: boolean;
  readonly tool: string;
  readonly callId: string;
  readonly onResolve: (approved: boolean) => void;
  readonly onDismiss: () => void;
}): React.JSX.Element | null {
  if (!props.open) {
    return null;
  }
  return (
    <div
      className="permModeModalOverlay toolApprovalModalOverlayZ"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tool-approval-title"
      onClick={props.onDismiss}
    >
      <div
        className="permModeModalCard"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <h2 id="tool-approval-title" className="permModeModalTitle">
          Подтверждение команды
        </h2>
        <p className="permModeModalDesc">
          Политика (ASK) требует явного согласия на выполнение инструмента в песочнице.
        </p>
        <div className="toolApprovalInfo">
          <span className="toolApprovalInfoLabel">Инструмент</span>
          <code className="toolApprovalInfoTool">{props.tool}</code>
          <span className="toolApprovalInfoCall" title={props.callId}>
            id: {props.callId.length > 36 ? `${props.callId.slice(0, 20)}…` : props.callId}
          </span>
        </div>
        <div className="toolApprovalActions">
          <button
            type="button"
            className="toolApprovalBtnReject"
            onClick={() => {
              props.onResolve(false);
            }}
          >
            Отклонить
          </button>
          <button
            type="button"
            className="toolApprovalBtnOk"
            onClick={() => {
              props.onResolve(true);
            }}
          >
            Разрешить
          </button>
        </div>
        <div className="permModeActions">
          <button type="button" className="permModeCancel" onClick={props.onDismiss}>
            Позже (как отклонить)
          </button>
        </div>
      </div>
    </div>
  );
}
