import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { CasesPage } from "./pages/Cases";
import { ComparePage } from "./pages/Compare";
import { CvRunsPage } from "./pages/CvRuns";
import { DashboardPage } from "./pages/Dashboard";
import { EvidencePage } from "./pages/Evidence";
import { ExportPage } from "./pages/Export";
import { InvestigationPage } from "./pages/Investigation";
import { WorkspacePage } from "./pages/Workspace";

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/investigation" element={<InvestigationPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/cv" element={<CvRunsPage />} />
          <Route path="/export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
