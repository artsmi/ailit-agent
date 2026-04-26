import React from "react";
import { createHashRouter, Navigate } from "react-router-dom";
import { AppShell } from "./shell/AppShell";
import { ChatPage } from "./views/ChatPage";
import { TeamPage } from "./views/TeamPage";
import { CurrentAgentsPage } from "./views/CurrentAgentsPage";
import { MemoryPage } from "./views/MemoryPage";
import { ProjectsPage } from "./views/ProjectsPage";
import { ReportsPage } from "./views/ReportsPage";
import { RuntimeStatusPage } from "./views/RuntimeStatusPage";

// Hash — иначе при `file://` (AppImage/prod) pathname = путь к index.html, а не "/",
// и BrowserRouter не матчит ни один route → пустой экран.
export const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate replace to="/chat" /> },
      { path: "chat", element: <ChatPage /> },
      { path: "team", element: <TeamPage /> },
      { path: "agents", element: <CurrentAgentsPage /> },
      { path: "memory", element: <MemoryPage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "runtime", element: <RuntimeStatusPage /> },
      { path: "agent-dialogue", element: <Navigate replace to="/team" /> },
      { path: "memory-graph", element: <Navigate replace to="/memory" /> },
      {
        path: "memory-graph-3d",
        element: <Navigate replace to={{ pathname: "/memory", search: "?v=3d" }} />
      }
    ]
  }
]);
