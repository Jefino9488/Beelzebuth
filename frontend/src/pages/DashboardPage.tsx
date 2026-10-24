/**
 * Operations dashboard.
 * Replaces the Jinja `dashboard.html` template: KPI cards, recent documents, audit trail
 * and live engine telemetry, all sourced from `/api/v1/console/dashboard`.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { FileText, Cpu, Database, HardDrive } from 'lucide-react';
import { useApiData } from '../lib/useApi';
import {
  PageHeader,
  Panel,
  StatCard,
  Table,
  Th,
  Td,
  Badge,
  Loading,
  Alert,
  EmptyState,
} from '../components/ui';

interface DashboardFile {
  id: string;
  name: string;
  organisation_id: string;
  organisation_name: string | null;
  format: string;
  version_count: number;
  file_hash: string | null;
  created_at: string;
}

interface AuditEntry {
  id: string;
  action: string;
  details: string | null;
  user_id: string | null;
  user_email: string | null;
  organisation_id: string | null;
  created_at: string;
}

interface DashboardPayload {
  stats: { org_count: number; user_count: number; file_count: number; audit_count: number };
  recent_files: DashboardFile[];
  audit_logs: AuditEntry[];
  engine: {
    database: string;
    vectorstore: string;
    verifier: string;
    device: string;
    model: string;
    workspace_dir: string;
    storage_dir: string;
  };
  is_super_admin: boolean;
  current_org_name: string;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const DashboardPage: React.FC = () => {
  const { data, loading, error } = useApiData<DashboardPayload>('/api/v1/console/dashboard');

  if (loading) return <Loading label="Loading dashboard…" />;
  if (error) return <Alert tone="rose">{error}</Alert>;
  if (!data) return null;

  return (
    <div>
      <PageHeader
        title="Operations Dashboard"
        description="Live tenant telemetry, ingestion activity and system health across the evidence pipeline."
      />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Documents"
          value={data.stats.file_count}
          hint="Indexed and searchable"
          tone="violet"
        />
        <StatCard
          label="Pipeline Executions"
          value={data.stats.audit_count}
          hint="Recorded in the audit trail"
          tone="emerald"
        />
        <StatCard label="Active Users" value={data.stats.user_count} tone="sky" />
        <StatCard label="Active Tenants" value={data.stats.org_count} tone="amber" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel
          title="Recent Activity"
          subtitle="Most recently ingested documents"
          className="xl:col-span-2"
          bodyClassName="p-0"
        >
          {data.recent_files.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<FileText className="h-7 w-7" />}
                title="No documents ingested yet"
                description="Upload a document to populate the evidence pipeline."
                action={
                  <Link
                    to="/documents"
                    className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-zinc-800"
                  >
                    Go to Documents
                  </Link>
                }
              />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Document</Th>
                  <Th>Tenant</Th>
                  <Th>Type</Th>
                  <Th>Versions</Th>
                  <Th>Created</Th>
                </tr>
              </thead>
              <tbody>
                {data.recent_files.map((file) => (
                  <tr key={file.id} className="hover:bg-zinc-900/40">
                    <Td>
                      <Link
                        to={`/documents/${file.id}/spans`}
                        className="flex items-center gap-1.5 text-zinc-200 transition hover:text-violet-300"
                      >
                        <FileText className="h-3 w-3 text-zinc-500" />
                        <span className="truncate">{file.name}</span>
                      </Link>
                    </Td>
                    <Td className="text-zinc-500">{file.organisation_name ?? 'Platform'}</Td>
                    <Td>
                      <Badge tone="neutral" mono>
                        {file.format}
                      </Badge>
                    </Td>
                    <Td className="font-mono text-zinc-500">v{file.version_count}</Td>
                    <Td className="whitespace-nowrap text-zinc-500">{formatTimestamp(file.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Engine Status" subtitle="Runtime telemetry">
            <dl className="space-y-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-zinc-500">
                  <Database className="h-3 w-3" /> Database
                </dt>
                <dd className="text-emerald-300">{data.engine.database}</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-zinc-500">
                  <HardDrive className="h-3 w-3" /> Vector Store
                </dt>
                <dd className="text-emerald-300">{data.engine.vectorstore}</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-zinc-500">
                  <Cpu className="h-3 w-3" /> Verifier
                </dt>
                <dd className="text-violet-300">{data.engine.verifier}</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-zinc-500">
                  <Cpu className="h-3 w-3" /> Device
                </dt>
                <dd className="text-zinc-300">{data.engine.device}</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-zinc-500">
                  <Cpu className="h-3 w-3" /> Model
                </dt>
                <dd className="truncate font-mono text-zinc-300">{data.engine.model}</dd>
              </div>
            </dl>
          </Panel>

          <Panel title="Recent Events" subtitle="Audit trail" bodyClassName="p-0">
            {data.audit_logs.length === 0 ? (
              <div className="p-4 text-center text-xs text-zinc-600">No audit events recorded yet.</div>
            ) : (
              <ul className="divide-y divide-zinc-800/60">
                {data.audit_logs.slice(0, 8).map((log) => (
                  <li key={log.id} className="px-4 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <Badge tone="violet" mono>
                        {log.action}
                      </Badge>
                      <span className="shrink-0 text-[10px] text-zinc-600">
                        {formatTimestamp(log.created_at)}
                      </span>
                    </div>
                    {log.details && (
                      <p className="mt-1 truncate text-[11px] text-zinc-500">{log.details}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;
