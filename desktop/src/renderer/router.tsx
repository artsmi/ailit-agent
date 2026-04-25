import React from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./shell/AppShell";
import { ChatPage } from "./views/ChatPage";
import { AgentDialoguePage } from "./views/AgentDialoguePage";
import { CurrentAgentsPage } from "./views/CurrentAgentsPage";
import { MemoryGraphPage } from "./views/MemoryGraphPage";
import { ProjectsPage } from "./views/ProjectsPage";
import { ReportsPage } from "./views/ReportsPage";
import { RuntimeStatusPage } from "./views/RuntimeStatusPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "chat", element: <ChatPage /> },
      { path: "agent-dialogue", element: <AgentDialoguePage /> },
      { path: "agents", element: <CurrentAgentsPage /> },
      { path: "memory-graph", element: <MemoryGraphPage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "runtime", element: <RuntimeStatusPage /> }
    ]
  }
]);

