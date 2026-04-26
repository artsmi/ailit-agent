import React from "react";

type CandyMaterialIconProps = {
  readonly name: string;
  readonly filled?: boolean;
};

/**
 * Material Symbols — как в референсе `ai_agent_ui_library_candy_style` (outlined, при active — FILL 1).
 */
export function CandyMaterialIcon({ name, filled = false }: CandyMaterialIconProps): React.JSX.Element {
  const base: string = "candyMaterialIcon material-symbols-outlined";
  const cl: string = filled ? `${base} candyMaterialIconFill` : base;
  return (
    <span aria-hidden="true" className={cl}>
      {name}
    </span>
  );
}
