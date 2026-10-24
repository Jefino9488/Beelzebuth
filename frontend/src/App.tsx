/**
 * Application root.
 *
 * Owns the client-side routing table for the console. This replaces the server-rendered
 * Jinja console: every page is now a React route.
 */

import React, { lazy, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';

const WorkstationPage = lazy(() => import('./pages/WorkstationPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const SpanInspectorPage = lazy(() => import('./pages/SpanInspectorPage'));
const ProcessGraphStudioPage = lazy(() => import('./pages/ProcessGraphStudioPage'));
const DefectRegisterPage = lazy(() => import('./pages/DefectRegisterPage'));
const AuditLogPage = lazy(() => import('./pages/AuditLogPage'));
const TenantAdminPage = lazy(() => import('./pages/TenantAdminPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

const App: React.FC = () => {
  useEffect(() => {
    document.title = 'Beelzebuth — Universal Document Digest & Diagram Engine';
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/workbench" replace />} />
          <Route path="/workbench" element={<WorkstationPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:fileId/spans" element={<SpanInspectorPage />} />
          <Route path="/process-graph" element={<ProcessGraphStudioPage />} />
          <Route path="/defects" element={<DefectRegisterPage />} />
          <Route path="/audit" element={<AuditLogPage />} />
          <Route path="/admin" element={<TenantAdminPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/workbench" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
