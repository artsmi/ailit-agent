import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { DesktopSessionProvider } from "./runtime/DesktopSessionContext";
import "./styles/app.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DesktopSessionProvider>
      <RouterProvider router={router} />
    </DesktopSessionProvider>
  </React.StrictMode>
);

