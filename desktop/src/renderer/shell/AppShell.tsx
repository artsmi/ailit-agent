import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { MockWorkspaceBadge } from "./MockWorkspaceBadge";

type NavItem = {
  readonly to: string;
  readonly label: string;
};

const NAV_ITEMS: readonly NavItem[] = [
  { to: "/chat", label: "Чат" },
  { to: "/agent-dialogue", label: "Диалог агентов" },
  { to: "/agents", label: "Текущие агенты" },
  { to: "/memory-graph", label: "Memory Graph" },
  { to: "/projects", label: "Проекты" },
  { to: "/reports", label: "Отчёты" },
  { to: "/runtime", label: "Runtime status" }
];

export function AppShell(): React.JSX.Element {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand" aria-label="ailit desktop">
          <div className="brandDot" />
          <div>
            <div className="brandTitle">ailit desktop</div>
            <div className="mono">mock-first • Candy</div>
          </div>
        </div>
        <nav className="nav" aria-label="Навигация">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "navLink navLinkActive" : "navLink")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="pill">
            <span>Workflow 9</span>
            <span className="mono">G9.1 mock</span>
          </div>
          <MockWorkspaceBadge />
        </header>
        <div className="page">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

