/**
 * Span inspector.
 * Replaces the Jinja `spans.html` template: a master/detail view over the immutable
 * granular evidence spans extracted from a document.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Workflow, Copy, Check, Hash } from 'lucide-react';
import { useApiData } from '../lib/useApi';
import {
  PageHeader,
  Panel,
  Badge,
  Button,
  EmptyState,
  Alert,
  Loading,
} from '../components/ui';

interface SpanEntry {
  span_id: string;
  page_number: string;
  text: string;
  location: string;
  section: string;
}

interface FileSpansPayload {
  file_id: string;
  file_name: string;
  organisation_name: string | null;
  spans: SpanEntry[];
}

export const SpanInspectorPage: React.FC = () => {
  const { fileId } = useParams<{ fileId: string }>();
  const { data, loading, error } = useApiData<FileSpansPayload>(
    fileId ? `/api/files/${fileId}/spans` : null
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const spans = useMemo(() => data?.spans ?? [], [data]);
  const selected = useMemo(
    () => spans.find((s) => s.span_id === selectedId) ?? spans[0] ?? null,
    [spans, selectedId]
  );

  useEffect(() => {
    if (!selectedId && spans.length > 0) setSelectedId(spans[0].span_id);
  }, [spans, selectedId]);

  const handleCopy = async () => {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(selected.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (loading) return <Loading label="Extracting evidence spans…" />;
  if (error) return <Alert tone="rose">{error}</Alert>;
  if (!data) return null;

  return (
    <div>
      <div className="mb-3">
        <Link
          to="/documents"
          className="inline-flex items-center gap-1.5 text-xs text-zinc-500 transition hover:text-zinc-300"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Documents
        </Link>
      </div>

      <PageHeader
        title={data.file_name}
        description="Immutable evidence spans extracted from the latest version of this document."
        action={
          <Link
            to={`/process-graph?file_id=${data.file_id}`}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition hover:from-violet-500 hover:to-indigo-500"
          >
            <Workflow className="h-3.5 w-3.5" />
            Process Graph
          </Link>
        }
      />

      {spans.length === 0 ? (
        <EmptyState
          icon={<Hash className="h-7 w-7" />}
          title="No spans extracted"
          description="This document produced no verifiable evidence spans. It may be empty or use an unsupported format."
          action={
            <Link
              to="/documents"
              className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-zinc-800"
            >
              Return to Documents
            </Link>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
          <Panel
            title={`Immutable Spans (${spans.length})`}
            className="lg:max-h-[calc(100vh-220px)] overflow-hidden"
            bodyClassName="scrollable-pane max-h-[calc(100vh-290px)] overflow-y-auto p-0"
          >
            <ul className="divide-y divide-zinc-800/60">
              {spans.map((span) => (
                <li key={span.span_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(span.span_id)}
                    className={`w-full px-3 py-2 text-left transition ${
                      selected?.span_id === span.span_id
                        ? 'bg-violet-950/40'
                        : 'hover:bg-zinc-900/60'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Badge tone="violet" mono>
                        {span.span_id}
                      </Badge>
                      <span className="text-[10px] text-zinc-600">
                        Page {span.page_number} • {span.text.length} chars
                      </span>
                    </div>
                    {span.section && (
                      <div className="mt-1 truncate text-[10px] text-zinc-500">§ {span.section}</div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="Verbatim Extracted Evidence"
            action={
              <Button onClick={handleCopy}>
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'Copied' : 'Copy Text'}
              </Button>
            }
            className="flex flex-col"
          >
            {selected ? (
              <>
                <pre className="scrollable-pane max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 font-mono text-[11px] leading-relaxed text-zinc-200 select-text">
                  {selected.text}
                </pre>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-zinc-600">
                  <Badge tone="violet" mono>
                    {selected.span_id}
                  </Badge>
                  <span>Page {selected.page_number}</span>
                  {selected.location && <span>• {selected.location}</span>}
                  {selected.section && <span>• {selected.section}</span>}
                  <span>• Immutable Provenance Status: Verified</span>
                </div>
              </>
            ) : null}
          </Panel>
        </div>
      )}
    </div>
  );
};

export default SpanInspectorPage;
