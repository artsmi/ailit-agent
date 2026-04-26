import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { NewDialogModal } from "../components/NewDialogModal";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { WorkspaceBadge } from "./WorkspaceBadge";

type NavItem = {
  readonly to: string;
  readonly label: string;
};

const NAV_ITEMS: readonly NavItem[] = [
  { to: "/chat", label: "Чат" },
  { to: "/agents", label: "Агенты" },
  { to: "/projects", label: "Проекты" },
  { to: "/team", label: "Команда" },
  { to: "/memory", label: "Память" },
  { to: "/reports", label: "Отчёты" },
  { to: "/runtime", label: "Runtime" }
];

export function AppShell(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const nav: ReturnType<typeof useNavigate> = useNavigate();
  const [openNew, setOpenNew] = React.useState(false);
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand" aria-label="Ailit">
          <div className="brandDot" />
          <div>
            <div className="brandTitle">Ailit</div>
          </div>
        </div>
        <button className="ctaNewDialog" type="button" onClick={() => setOpenNew(true)}>
          + Новый диалог
        </button>
        <nav className="nav" aria-label="Навигация">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              className={({ isActive }) => (isActive ? "navLink navLinkActive" : "navLink")}
              to={item.to}
            >
              {item.label}
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
          s.createNewChatSession(ids, `Session ${n}`);
          setOpenNew(false);
          nav("/chat");
        }}
      />
    </div>
  );
}
