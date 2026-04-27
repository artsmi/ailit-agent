import React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CandyCodeCopyButton } from "./CandyCodeCopyButton";

type CandyMarkdownBodyProps = {
  readonly text: string;
};

type CodeElementProps = {
  readonly children?: React.ReactNode;
  readonly className?: string;
};

type CodeBlockMeta = {
  readonly copyText: string;
  readonly language: string;
  readonly title: string;
};

function nodeText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map((item: React.ReactNode): string => nodeText(item)).join("");
  }
  if (React.isValidElement<CodeElementProps>(node)) {
    return nodeText(node.props.children);
  }
  return "";
}

function languageTitle(language: string): string {
  if (language.trim() === "") {
    return "code";
  }
  return language.trim();
}

function codeBlockMeta(children: React.ReactNode): CodeBlockMeta {
  const onlyChild: React.ReactNode = React.Children.toArray(children)[0];
  if (!React.isValidElement<CodeElementProps>(onlyChild)) {
    return { copyText: nodeText(children).trimEnd(), language: "", title: "code" };
  }

  const className: string = onlyChild.props.className ?? "";
  const match: RegExpMatchArray | null = /language-([^\s]+)/.exec(className);
  const language: string = match?.[1] ?? "";
  return {
    copyText: nodeText(onlyChild.props.children).trimEnd(),
    language,
    title: languageTitle(language)
  };
}

const markdownComponents: Components = {
  a: ({ children, ...props }) => (
    <a {...props} rel="noreferrer noopener" target="_blank">
      {children}
    </a>
  ),
  pre: ({ children, ...props }) => {
    const meta: CodeBlockMeta = codeBlockMeta(children);
    return (
      <div className="markdownCodeBlock" data-code-language={meta.language || "plain"}>
        <div className="markdownCodeBlockHead">
          <span className="markdownCodeBlockTitle">{meta.title}</span>
          <CandyCodeCopyButton text={meta.copyText} />
        </div>
        <pre {...props}>{children}</pre>
      </div>
    );
  },
  table: ({ children, ...props }) => (
    <div className="markdownBodyTableWrap">
      <table {...props}>{children}</table>
    </div>
  )
};

/**
 * Рендер MD+GFM в духе референса `ai_agent_minimalist_chat_candy_style` (класс `markdown-body`).
 */
export function CandyMarkdownBody({ text }: CandyMarkdownBodyProps): React.JSX.Element {
  return (
    <div className="markdownBody">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
