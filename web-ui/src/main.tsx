import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import AIReviewPage from './pages/AIReviewPage';
import SimulationConfigPage from './pages/SimulationConfigPage';
import ResultsViewerPage from './pages/ResultsViewerPage';
import RuleViolationsPage from './pages/RuleViolationsPage';
import ThermalMapViewer from './components/ThermalMapViewer';
import AnalysisReportPage from './pages/AnalysisReportPage';
import RuleEditorPage from './pages/RuleEditorPage';
import FindingsViewerPage from './pages/FindingsViewerPage';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <div className="app">
      <header className="header">
        <div className="container">
          <h1>
            <Link to="/" className="logo-link">PCB & EM Simulation Copilot</Link>
          </h1>
          <nav>
            <Link to="/" className="nav-link">Projects</Link>
          </nav>
        </div>
      </header>
      
      <main className="main">
        <div className="container">
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="/projects/:projectId/ai-review" element={<AIReviewPage />} />
            <Route path="/projects/:projectId/simulations/new" element={<SimulationConfigPage />} />
            <Route path="/simulations/runs/:runId" element={<ResultsViewerPage />} />

            {/* AI Review Findings Route */}
            <Route path="/reviews/:reviewId/findings" element={<FindingsViewerPage />} />

            {/* Design Rule & Analysis Routes */}
            <Route path="/projects/:projectId/layouts/:layoutId/violations" element={<RuleViolationsPage />} />
            <Route path="/projects/:projectId/layouts/:layoutId/thermal" element={<ThermalMapViewer />} />
            <Route path="/projects/:projectId/layouts/:layoutId/report" element={<AnalysisReportPage />} />
            <Route path="/projects/:projectId/rules" element={<RuleEditorPage />} />
          </Routes>
        </div>
      </main>
      
      <footer className="footer">
        <div className="container">
          <p>AI-powered PCB design and EM simulation analysis</p>
        </div>
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
