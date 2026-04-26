import React from "react";

type ChatLayoutValue = {
  readonly openNewDialog: () => void;
};

const Ctx = React.createContext<ChatLayoutValue | null>(null);

export function ChatLayoutProvider({ children, value }: { readonly children: React.ReactNode; readonly value: ChatLayoutValue }): React.JSX.Element {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChatLayout(): ChatLayoutValue {
  const v: ChatLayoutValue | null = React.useContext(Ctx);
  if (!v) {
    throw new Error("useChatLayout: provider missing (wrap with ChatLayoutProvider in AppShell).");
  }
  return v;
}
