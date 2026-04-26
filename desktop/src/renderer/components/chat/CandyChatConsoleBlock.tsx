import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

const PREVIEW_LINES: number = 5;

type CandyChatConsoleBlockProps = {
  readonly shell: string;
  readonly text: string;
  /** `compact` — мелкий шрифт для tool.* (не shell). */
  readonly variant?: "normal" | "compact";
};

/**
 * Блок вывода консоли (tool/shell) в стиле `ai_agent_minimalist_chat_candy_style`.
 */
export function CandyChatConsoleBlock(p: CandyChatConsoleBlockProps): React.JSX.Element {
  const shell: string = p.shell;
  const text: string = p.text;
  const variant: "normal" | "compact" = p.variant ?? "normal";
  const lines: readonly string[] = text.split(/\r?\n/);
  const preview: readonly string[] = lines.slice(0, PREVIEW_LINES);
  const rest: readonly string[] = lines.slice(PREVIEW_LINES);
  const hasMore: boolean = rest.length > 0;
  return (
    <div
      className={
        variant === "compact" ? "candyChatConsole candyChatConsoleCompact" : "candyChatConsole"
      }
      data-candy-console="1"
    >
      <div className="candyChatConsoleInner">
        <div className="candyChatConsoleHead">
          <span className="candyChatConsoleHeadLabel">Console output</span>
          <span className="candyChatConsoleHeadShell">{shell}</span>
        </div>
        <div className="candyChatConsoleBody">
          <div className="candyChatConsolePre">
            {preview.map((line, i) => (
              <div className="candyChatConsoleLine" key={`p-${i}`}>
                {line}
              </div>
            ))}
          </div>
          {hasMore ? (
            <details className="candyChatConsoleDetails">
              <summary className="candyChatConsoleMore">
                <span>Показать полностью</span>
                <span className="candyChatConsoleMoreIconWrap" aria-hidden="true">
                  <CandyMaterialIcon filled name="expand_more" />
                </span>
              </summary>
              <div className="candyChatConsoleRest">
                {rest.map((line, i) => (
                  <div className="candyChatConsoleLine" key={`r-${i}`}>
                    {line}
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}
