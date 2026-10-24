/**
 * Audit log viewer.
 * Replaces the Jinja `audit.html` template with a searchable, tenant-scoped event stream.
 */

import React, { useMemo, useState } from 'react';
import { Search, ScrollText } from 'lucide-react';
import { useApiData } from '../lib/useApi';
import {
  PageHeader,
  Panel,
  Table,
  Th,
  Td,
  Badge,
  EmptyState,
  Alert,
  Loading,
  inputClass,
} from '../components/ui';

interface AuditEntry {
  id: string;
  action: string;
  details: string | null;
  user_id: string | null;
  user_email: string | null;
  organisation_id: string | null;
  created_at: string;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export const AuditLogPage: React.FC = () => {
  const { data, loading, error } = useApiData<AuditEntry[]>('/api/v1/console/audit-logs?limit=100');
  const [search, setSearch] = useState('');

  const logs = useMemo(() => data ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return logs;
    return logs.filter((log) =>
      `${log.action} ${log.details ?? ''} ${log.user_email ?? ''}`.toLowerCase().includes(needle)
    );
  }, [logs, search]);

  if (loading) return <Loading label="Loading audit trail…" />;
  if (error) return <Alert tone="rose">{error}</Alert>;

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        description="System events and verification telemetry, scoped to the tenants you are authorised to observe."
        action={
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search events…"
              className={`${inputClass} pl-8`}
            />
          </div>
        }
      />

      <Panel title={`Recorded Events (${filtered.length})`} bodyClassName="p-0">
        {filtered.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<ScrollText className="h-7 w-7" />}
              title="No audit log events recorded yet"
              description="Pipeline executions, uploads and configuration changes will appear here."
            />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Event</Th>
                <Th>User</Th>
                <Th>Tenant</Th>
                <Th>Details</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => (
                <tr key={log.id} className="hover:bg-zinc-900/40">
                  <Td className="whitespace-nowrap font-mono text-[10px] text-zinc-500">
                    {formatTimestamp(log.created_at)}
                  </Td>
                  <Td>
                    <Badge tone="violet" mono>
                      {log.action}
                    </Badge>
                  </Td>
                  <Td className="text-zinc-400">{log.user_email ?? 'system'}</Td>
                  <Td className="font-mono text-[10px] text-zinc-600">
                    {log.organisation_id ?? 'platform'}
                  </Td>
                  <Td className="max-w-xl text-[11px] text-zinc-500">{log.details ?? 'Success'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
};

export default AuditLogPage;
