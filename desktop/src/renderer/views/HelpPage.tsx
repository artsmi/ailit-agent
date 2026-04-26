import React from "react";

/** Минимальная страница по маршруту /help: пункт «Справка» в боковом футере. */
export function HelpPage(): React.JSX.Element {
  return (
    <div className="page pageSingle">
      <div className="pageTitleRow">
        <h2 className="sectionTitle">Справка</h2>
      </div>
      <div className="card">
        <div className="cardBody">Документация и подсказки — в каталоге docs репозитория и в README.</div>
      </div>
    </div>
  );
}
