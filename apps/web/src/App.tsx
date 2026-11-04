import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { ReplayPage } from "./pages/ReplayPage";
import { InvestigationsPage } from "./pages/InvestigationsPage";
import { InvestigationPage } from "./pages/InvestigationPage";
import { DataSourcesPage } from "./pages/DataSourcesPage";
import { EvaluationPage } from "./pages/EvaluationPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="/replay" element={<ReplayPage />} />
        <Route path="/investigations" element={<InvestigationsPage />} />
        <Route path="/investigations/:caseId" element={<InvestigationPage />} />
        <Route path="/data" element={<DataSourcesPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
