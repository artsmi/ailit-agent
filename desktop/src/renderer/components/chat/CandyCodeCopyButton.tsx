import React from "react";

type CandyCodeCopyButtonProps = {
  readonly text: string;
  readonly className?: string;
};

type CopyState = "idle" | "copied" | "error";

/**
 * Общая copy-кнопка для markdown code blocks и console output.
 */
export function CandyCodeCopyButton({ text, className }: CandyCodeCopyButtonProps): React.JSX.Element {
  const [copyState, setCopyState] = React.useState<CopyState>("idle");
  const resetTimerRef = React.useRef<number | null>(null);

  React.useEffect((): (() => void) => {
    return (): void => {
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  const resetLater = React.useCallback((): void => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    resetTimerRef.current = window.setTimeout((): void => setCopyState("idle"), 1400);
  }, []);

  const copyText = React.useCallback(async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    } finally {
      resetLater();
    }
  }, [resetLater, text]);

  const label: string = copyState === "copied" ? "Copied" : copyState === "error" ? "Error" : "Copy";

  return (
    <button
      aria-label="Copy code"
      className={className === undefined ? "candyCodeCopyBtn" : `candyCodeCopyBtn ${className}`}
      data-copy-state={copyState}
      onClick={copyText}
      type="button"
    >
      {label}
    </button>
  );
}
