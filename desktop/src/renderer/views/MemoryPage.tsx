import React from "react";
import { useSearchParams } from "react-router-dom";

import { MemoryGraph3DPage } from "./MemoryGraph3DPage";
import { MemoryGraphPage } from "./MemoryGraphPage";

type Mode = "2d" | "3d";

/**
 * «Память» — 2D (список/паг) и 3D, переключение на странице. По умолчанию 2D.
 */
export function MemoryPage(): React.JSX.Element {
  const [sp, setSp] = useSearchParams();
  const mode: Mode = sp.get("v") === "3d" ? "3d" : "2d";
  const setMode: (m: Mode) => void = (m) => {
    setSp(
      (prev) => {
        const p: URLSearchParams = new URLSearchParams(prev);
        if (m === "2d") {
          p.delete("v");
        } else {
          p.set("v", "3d");
        }
        return p;
      },
      { replace: true }
    );
  };
  return (
    <div className="pageSingle memStack memPageRoot">
      <div className="memoryModeBar" role="tablist">
        <div className="sectionTitle smTitle">Память</div>
        <div className="memToggle" role="group" aria-label="view">
          <button
            className={mode === "2d" ? "pill memToggleOn" : "pill"}
            type="button"
            onClick={() => {
              setMode("2d");
            }}
            role="tab"
          >
            2D
          </button>
          <button
            className={mode === "3d" ? "pill memToggleOn" : "pill"}
            type="button"
            onClick={() => {
              setMode("3d");
            }}
            role="tab"
          >
            3D
          </button>
        </div>
      </div>
      {mode === "2d" ? (
        <div className="memChild">
          <MemoryGraphPage />
        </div>
      ) : (
        <div className="memChild">
          <MemoryGraph3DPage noInitialAutoZoom />
        </div>
      )}
    </div>
  );
}
