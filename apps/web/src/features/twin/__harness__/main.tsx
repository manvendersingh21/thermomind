/**
 * DEV-ONLY harness (not part of the app build): mimics the App.tsx wiring.
 *   http://localhost:5174/src/features/twin/__harness__/index.html#/twin/<caseId>
 *   http://localhost:5174/src/features/twin/__harness__/index.html#/embed/<caseId>
 */
import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Route, Routes, useParams } from "react-router-dom";
import "../../../styles.css";
import { TwinEmbed } from "../TwinEmbed";

const TwinPage = lazy(() => import("../TwinPage"));

function Embed() {
  const { caseId } = useParams();
  return (
    <div className="max-w-3xl">
      <TwinEmbed caseId={caseId} height={420} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <div className="min-h-screen bg-ink-900 p-4 text-ink-100">
        <Suspense fallback={<div>Loading…</div>}>
          <Routes>
            <Route path="/twin" element={<TwinPage />} />
            <Route path="/twin/:caseId" element={<TwinPage />} />
            <Route path="/embed/:caseId" element={<Embed />} />
            <Route path="*" element={<TwinPage />} />
          </Routes>
        </Suspense>
      </div>
    </HashRouter>
  </React.StrictMode>,
);
