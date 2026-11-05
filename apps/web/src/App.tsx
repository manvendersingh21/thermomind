import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { ReplayPage } from "./pages/ReplayPage";
import { InvestigationsPage } from "./pages/InvestigationsPage";
import { InvestigationPage } from "./pages/InvestigationPage";
import { DataSourcesPage } from "./pages/DataSourcesPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { AskPage, InboxPage } from "./plant";
import PlannerPage from "./features/planner/PlannerPage";
import InstrumentsPage from "./features/instruments/InstrumentsPage";
import EmissionsPage from "./features/emissions/EmissionsPage";
import GridPage from "./features/grid/GridPage";
import ConnectorsPage from "./features/connectors/ConnectorsPage";
import OpsPage from "./features/ops/OpsPage";
import ThermalPage from "./features/thermal/ThermalPage";
import ComparePage from "./features/compare/ComparePage";
import CaseReportPage from "./features/report/CaseReportPage";
import AgentTreePage from "./features/agents_tree/AgentTreePage";
import AutonomyPage from "./features/collab/AutonomyPage";
import OnboardingPage from "./features/collab/OnboardingPage";
import ProposePage from "./features/deliberation/ProposePage";
import ExecutivePage from "./features/executive/ExecutivePage";
import WatchdogPage from "./features/watchdog/WatchdogPage";

const SimulatorPage = lazy(() => import("./features/simulator/SimulatorPage"));
const TwinPage = lazy(() => import("./features/twin/TwinPage"));
const twin = (
  <Suspense fallback={<div className="p-6 text-sm text-ink-400">Loading 3D twin…</div>}>
    <TwinPage />
  </Suspense>
);

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
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/investigations/:caseId/report" element={<CaseReportPage />} />
        <Route path="/planner" element={<PlannerPage />} />
        <Route path="/instruments" element={<InstrumentsPage />} />
        <Route path="/emissions" element={<EmissionsPage />} />
        <Route path="/grid" element={<GridPage />} />
        <Route path="/thermal" element={<ThermalPage />} />
        <Route path="/connectors" element={<ConnectorsPage />} />
        <Route path="/ops" element={<OpsPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/agents" element={<AgentTreePage />} />
        <Route path="/autonomy" element={<AutonomyPage />} />
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/propose" element={<ProposePage />} />
        <Route path="/executive" element={<ExecutivePage />} />
        <Route path="/watchdog" element={<WatchdogPage />} />
        <Route path="/simulator" element={<Suspense fallback={<div className="p-6 text-sm text-ink-400">Loading simulator…</div>}><SimulatorPage /></Suspense>} />
        <Route path="/twin" element={twin} />
        <Route path="/twin/:caseId" element={twin} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
