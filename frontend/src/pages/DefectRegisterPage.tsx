/**
 * Defect Register.
 * Replaces the Jinja `defects.html` template with a filtered, tenant-scoped view of the
 * claims that were quarantined by the System-1 verifier.
 */

import React, { useMemo, useState } from 'react';
import { ShieldAlert, ShieldCheck, Search } from 'lucide-react';
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

interface DefectEntry {
  id: string | null;
  category: string | null;
  severity: string | null;
  claimed_statement: string | null;
  rationale: string | null;
  confidence: number | null;
  evidence_spans: string[];
  evidence_text: string | null;
  document_name: string | null;
}

type Filter = 'all' | 'open' | 'resolved';

const SEVERITY_TONE: Record<string, 'rose' | 'amber' | 'neutral'> = {
  HIGH: 'rose',
  MEDIUM: 'amber',
  LOW: 'neutral',
};

export const DefectRegisterPage: React.FC = () => {
  const { data, loading, error } = useApiData<DefectEntry[]>('/api/v1/console/defects');
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');

  const defects = useMemo(() => data ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return defects.filter((defect) => {
      if (needle) {
        const haystack = `${defect.claimed_statement ?? ''} ${defect.rationale ?? ''}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      if (filter === 'open') return defect.severity !== 'LOW';
      if (filter === 'resolved') return defect.severity === 'LOW';
      return true;
    });
  }, [defects, filter, search]);

  if (loading) return <Loading label="Loading defect register…" />;
  if (error) return <Alert tone="rose">{error}</Alert>;

  return (
    <div>
      <PageHeader
        title="Ambiguity & Defect Register"
        description="Claims that were not strictly entailed by the source evidence are quarantined here instead of being forced into the authoritative process graph."
        action={
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search defects…"
              className={`${inputClass} pl-8`}
            />
          </div>
        }
      />

      <div className="mb-3 flex gap-1.5">
        {(['all', 'open', 'resolved'] as Filter[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={`rounded-lg border px-3 py-1 text-[11px] font-medium capitalize transition ${
              filter === value
                ? 'border-violet-500 bg-violet-950/50 text-violet-200'
                : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:bg-zinc-800'
            }`}
          >
            {value}
          </button>
        ))}
      </div>

      <Panel title={`Quarantined Claims (${filtered.length})`} bodyClassName="p-0">
        {filtered.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<ShieldCheck className="h-7 w-7 text-emerald-500" />}
              title="Zero Active Defects"
              description="All claims were strictly entailed by the source evidence spans."
            />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Document</Th>
                <Th>Category</Th>
                <Th>Severity</Th>
                <Th>Quarantined Claim</Th>
                <Th>Cited Spans</Th>
                <Th>Evidence</Th>
                <Th>Rationale</Th>
                <Th>Confidence</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((defect, index) => (
                <tr key={defect.id ?? index} className="hover:bg-zinc-900/40">
                  <Td className="text-zinc-500">{defect.document_name ?? 'Policy Document'}</Td>
                  <Td>
                    <Badge tone="amber" mono>
                      {defect.category?.replace(/_/g, ' ') ?? 'UNCATEGORISED'}
                    </Badge>
                  </Td>
                  <Td>
                    <Badge tone={SEVERITY_TONE[defect.severity ?? 'LOW'] ?? 'neutral'}>
                      {defect.severity ?? 'LOW'}
                    </Badge>
                  </Td>
                  <Td className="max-w-xs text-zinc-200">{defect.claimed_statement ?? '—'}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {(defect.evidence_spans ?? []).map((span) => (
                        <Badge key={span} tone="violet" mono>
                          {span}
                        </Badge>
                      ))}
                    </div>
                  </Td>
                  <Td className="max-w-xs text-[11px] text-zinc-500">
                    {defect.evidence_text?.slice(0, 80)}
                    {defect.evidence_text && defect.evidence_text.length > 80 ? '…' : ''}
                  </Td>
                  <Td className="max-w-xs text-[11px] text-rose-300/80">{defect.rationale ?? '—'}</Td>
                  <Td className="font-mono text-zinc-400">{defect.confidence?.toFixed(2) ?? '—'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      <p className="mt-3 flex items-center gap-1.5 text-[10px] text-zinc-600">
        <ShieldAlert className="h-3 w-3" />
        Quarantined claims never enter the authoritative process graph AST.
      </p>
    </div>
  );
};

export default DefectRegisterPage;
