import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DesktopSessionProvider } from "../runtime/DesktopSessionContext";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("renders navigation and brand", () => {
    render(
      <MemoryRouter>
        <DesktopSessionProvider>
          <AppShell />
        </DesktopSessionProvider>
      </MemoryRouter>
    );
    expect(screen.getByLabelText("Ailit")).toBeInTheDocument();
    expect(screen.getByLabelText("Навигация")).toBeInTheDocument();
  });
});

