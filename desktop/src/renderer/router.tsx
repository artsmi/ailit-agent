import React from "react";
import { createHashRouter, Navigate } from "react-router-dom";
import { AppShell } from "./shell/AppShell";
import { ChatPage } from "./views/ChatPage";
import { AgentDialoguePage } from "./views/AgentDialoguePage";
import { CurrentAgentsPage } from "./views/CurrentAgentsPage";
import { MemoryGraphPage } from "./views/MemoryGraphPage";
import { MemoryGraph3DPage } from "./views/MemoryGraph3DPage";
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
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "chat", element: <ChatPage /> },
      { path: "agent-dialogue", element: <AgentDialoguePage /> },
      { path: "agents", element: <CurrentAgentsPage /> },
      { path: "memory-graph", element: <MemoryGraphPage /> },
      { path: "memory-graph-3d", element: <MemoryGraph3DPage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "runtime", element: <RuntimeStatusPage /> }
    ]
  }
]);

