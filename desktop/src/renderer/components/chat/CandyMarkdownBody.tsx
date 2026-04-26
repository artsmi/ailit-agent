import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type CandyMarkdownBodyProps = {
  readonly text: string;
};

/**
 * Рендер MD+GFM в духе референса `ai_agent_minimalist_chat_candy_style` (класс `markdown-body`).
 */
export function CandyMarkdownBody({ text }: CandyMarkdownBodyProps): React.JSX.Element {
  return (
    <div className="markdownBody">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => (
            <a {...props} rel="noreferrer noopener" target="_blank">
              {children}
            </a>
          ),
          table: ({ children, ...props }) => (
            <div className="markdownBodyTableWrap">
              <table {...props}>{children}</table>
            </div>
          )
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
