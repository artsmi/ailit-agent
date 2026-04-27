import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";
import { type ParsedConsoleBlock, parseConsoleBlockText } from "./consoleBlockModel";

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
  const parsed: ParsedConsoleBlock = React.useMemo((): ParsedConsoleBlock => parseConsoleBlockText(text), [text]);
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
            <div className="candyChatConsoleLine candyChatConsoleCmd">{parsed.titleLine}</div>
            {parsed.contentLines.length === 0
              ? null
              : parsed.hasExpandable
                ? (parsed.previewOutLines as string[]).map((line, i) => {
                    return (
                    <div
                      className="candyChatConsoleLine candyChatConsoleOutLine"
                      key={`p-${i}-${String(line).slice(0, 32)}`}
                    >
                      {line}
                    </div>
                    );
                  })
                : (parsed.contentLines as string[]).map((line, i) => {
                    return (
                    <div
                      className="candyChatConsoleLine candyChatConsoleOutLine"
                      key={`a-${i}-${String(line).slice(0, 32)}`}
                    >
                      {line}
                    </div>
                    );
                  })}
          </div>
          {parsed.hasExpandable ? (
            <details className="candyChatConsoleDetails">
              <summary className="candyChatConsoleMore">
                <span className="candyChatConsoleMoreText">Показать полностью</span>
                <span className="candyChatConsoleMoreIconWrap" aria-hidden="true">
                  <CandyMaterialIcon filled name="expand_more" />
                </span>
              </summary>
              <div className="candyChatConsoleRest">
                {(parsed.fullTextLines as string[]).map((line, i) => {
                  return (
                  <div
                    className="candyChatConsoleLine candyChatConsoleOutLine"
                    key={`e-${i}-${String(line).slice(0, 32)}`}
                  >
                    {line}
                  </div>
                  );
                })}
              </div>
            </details>
          ) : null}
        </div>
        {typeof parsed.statusDetail === "string" && (parsed.status === "ok" || parsed.status === "error") ? (
          <div
            className={
              parsed.status === "ok" ? "candyChatConsoleStatusRow candyChatConsoleStatusOk" : "candyChatConsoleStatusRow candyChatConsoleStatusErr"
            }
          >
            {parsed.statusDetail}
          </div>
        ) : null}
      </div>
    </div>
  );
}
