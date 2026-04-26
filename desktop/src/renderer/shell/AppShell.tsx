import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { NewDialogModal } from "../components/NewDialogModal";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { ChatLayoutProvider } from "./ChatLayoutContext";
import { CandyMaterialIcon } from "./CandyMaterialIcon";
import { WorkspaceBadge } from "./WorkspaceBadge";

type CandyNavItem = {
  readonly to: string;
  readonly label: string;
  readonly icon: string;
};

const NAV_ITEMS: readonly CandyNavItem[] = [
  { to: "/chat", label: "Чат", icon: "forum" },
  { to: "/agents", label: "Агенты", icon: "smart_toy" },
  { to: "/projects", label: "Проекты", icon: "folder_open" },
  { to: "/team", label: "Команда", icon: "groups" },
  { to: "/memory", label: "Память", icon: "hub" },
  { to: "/reports", label: "Отчёты", icon: "bar_chart" },
  { to: "/runtime", label: "Параметры", icon: "settings" },
  { to: "/help", label: "Справка", icon: "help_outline" }
];

function navClassName(isActive: boolean): string {
  return isActive ? "candyNavLink candyNavLinkActive" : "candyNavLink";
}

export function AppShell(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const nav: ReturnType<typeof useNavigate> = useNavigate();
  const [openNew, setOpenNew] = React.useState(false);
  const openNewDialog: () => void = React.useCallback(() => setOpenNew(true), []);
  return (
    <ChatLayoutProvider value={{ openNewDialog }}>
      <div className="app">
        <aside className="candySideNav" aria-label="Боковая панель">
          <div className="candySideNavBrand" aria-label="Ailit">
            <h1 className="candyBrandTitle">Ailit</h1>
          </div>
          <button className="candySideNavCta" type="button" onClick={() => setOpenNew(true)}>
            <CandyMaterialIcon name="add" filled />
            <span>Новый диалог</span>
          </button>
          <nav className="candySideNavMain" aria-label="Навигация">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => navClassName(isActive)}>
                {({ isActive }) => (
                  <>
                    <CandyMaterialIcon name={item.icon} filled={isActive} />
                    <span className="candyNavLinkLabel">{item.label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="main">
          <header className="topbar">
            <WorkspaceBadge />
          </header>
          <div className="page">
            <Outlet />
          </div>
        </main>
        <NewDialogModal
          open={openNew}
          projects={s.registry}
          onClose={() => setOpenNew(false)}
          onCreate={(ids) => {
            if (ids.length === 0) {
              return;
            }
            const n: number = s.sessions.length + 1;
            s.createNewChatSession(ids, `Диалог ${n}`);
            setOpenNew(false);
            nav("/chat");
          }}
        />
      </div>
    </ChatLayoutProvider>
  );
}
