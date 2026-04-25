import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("renders navigation and brand", () => {
    render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    );
    expect(screen.getByLabelText("ailit desktop")).toBeInTheDocument();
    expect(screen.getByLabelText("Навигация")).toBeInTheDocument();
  });
});

