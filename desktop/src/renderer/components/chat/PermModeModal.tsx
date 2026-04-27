import React from "react";

const MODES: ReadonlyArray<{ readonly id: string; readonly label: string; readonly hint: string }> = [
  { id: "read", label: "read", hint: "Только чтение, KB" },
  { id: "read_plan", label: "read_plan", hint: "Доки/план" },
  { id: "explore", label: "explore", hint: "Shell+read" },
  { id: "edit", label: "edit", hint: "Полные инструменты" }
];

/**
 * Модалка not_sure (Candy: скругления, primary/secondary из глобальных стилей).
 */
export function PermModeModal(props: {
  readonly open: boolean;
  readonly onSelect: (mode: string, remember: boolean) => void;
  readonly onDismiss: () => void;
}): React.JSX.Element | null {
  const [remember, setRemember] = React.useState(false);
  if (!props.open) {
    return null;
  }
  return (
    <div
      className="permModeModalOverlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="perm-mode-title"
      onClick={props.onDismiss}
    >
      <div
        className="permModeModalCard"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <h2 id="perm-mode-title" className="permModeModalTitle">
          Режим политики (perm-5)
        </h2>
        <p className="permModeModalDesc">
          Классификатор не уверен. Выберите набор инструментов для этого хода.
        </p>
        <div className="permModeGrid">
          {MODES.map((m) => (
            <button
              type="button"
              key={m.id}
              className="permModeOption"
              onClick={() => {
                props.onSelect(m.id, remember);
              }}
            >
              <span className="permModeOptionLabel">{m.label}</span>
              <span className="permModeOptionHint">{m.hint}</span>
            </button>
          ))}
        </div>
        <label className="permModeRemember">
          <input
            type="checkbox"
            checked={remember}
            onChange={() => {
              setRemember((v) => !v);
            }}
          />
          <span>Запомнить для проекта</span>
        </label>
        <div className="permModeActions">
          <button type="button" className="permModeCancel" onClick={props.onDismiss}>
            Позже
          </button>
        </div>
      </div>
    </div>
  );
}
