import React from "react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { DesktopSessionProvider } from "../runtime/DesktopSessionContext";
import { RECALL_UI_PHRASE_WHITELIST } from "../runtime/memoryRecallUiPhaseProjection";
import { MemoryGraph3DPage } from "./MemoryGraph3DPage";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterAll(() => {
  vi.unstubAllGlobals();
});

vi.mock("react-force-graph-3d", () => ({
  __esModule: true,
  default: function MockForceGraph3D(): React.JSX.Element {
    return <div data-testid="mock-force-graph-3d" />;
  }
}));

describe("MemoryGraph3DPage", () => {
  it("does not render recall whitelist strings inside mem3dRoot (UC-06)", () => {
    render(
      <MemoryRouter>
        <DesktopSessionProvider>
          <MemoryGraph3DPage />
        </DesktopSessionProvider>
      </MemoryRouter>
    );
    const root: Element | null = document.querySelector(".mem3dRoot");
    expect(root).not.toBeNull();
    const t: string = (root?.textContent ?? "").replace(/\s+/g, " ");
    for (const entry of RECALL_UI_PHRASE_WHITELIST) {
      expect(t).not.toContain(entry.text);
    }
  });
});
