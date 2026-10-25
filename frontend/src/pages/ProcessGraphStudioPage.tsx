/**
 * Process Graph Studio.
 * Replaces the Jinja `process_graph.html` template with a routed, multi-projection
 * workbench: canonical AST graph, Mermaid flowchart / swimlane / state machine,
 * BPMN 2.0 XML, the Ambiguity & Defect Register, and the raw AST JSON.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ReactFlow, Background, Controls, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Workflow,
  Upload,
  Play,
  Download,
  FileText,
  AlertTriangle,
  Boxes,
  GitBranch,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApiData } from '../lib/useApi';
import {
  PageHeader,
  Panel,
  TabBar,
  Table,
  Th,
  Td,
  Badge,
  Button,
  EmptyState,
  Alert,
  StatCard,
  Field,
  selectClass,
  CodeBlock,
  downloadText,
  cn,
} from '../components/ui';

/* ------------------------------------------------------------------ */
/* Wire types                                                          */
/* ------------------------------------------------------------------ */

interface ProcessActivity {
  id: string;
  actor_id: string;
  label: string;
  description: string;
  evidence: string[];
  modality: string;
  temporal_order: number;
}
interface ProcessGateway {
  id: string;
  question: string;
  gateway_type: string;
  evidence: string[];
  actor_id: string | null;
}
interface ProcessEvent {
  id: string;
  type: 'start' | 'end' | 'intermediate';
  label: string;
  evidence: string[];
}
interface ProcessTransition {
  id: string;
  from_id: string;
  to_id: string;
  relation: string;
  label: string | null;
  condition: string | null;
  evidence: string[];
  is_loop: boolean;
}
interface GraphPayload {
  process_name: string;
  objective: string;
  events: ProcessEvent[];
  actors: { id: string; name: string; evidence: string[] }[];
  activities: ProcessActivity[];
  gateways: ProcessGateway[];
  transitions: ProcessTransition[];
}
interface DefectRecord {
  proposition_id: string;
  evidence_spans: string[];
  defect_category: string;
  claimed_statement: string;
  evidence_text: string;
  rationale: string;
  confidence: number;
  actor_involved: string | null;
}
interface DefectRegister {
  document_name: string;
  total_propositions_extracted: number;
  propositions_supported: number;
  propositions_uncertain: number;
  propositions_unsupported: number;
  defects: DefectRecord[];
}
interface GraphResponse {
  document_name: string;
  process_name: string;
  objective: string;
  metrics: {
    activities_count: number;
    gateways_count: number;
    transitions_count: number;
    actors_count: number;
    defects_quarantined_count: number;
  };
  latencies: {
    extraction_sec: number;
    laya_sec: number;
    compilation_sec: number;
    total_sec: number;
  };
  graph: GraphPayload;
  defect_register: DefectRegister;
  bpmn_2_0_xml: string;
  flowchart_mermaid: string;
  swimlane_mermaid: string;
  state_machine_mermaid: string | null;
  digital_markdown: string;
}

interface FileRecord {
  id: string;
  name: string;
  organisation_id: string;
  versions: unknown[];
}

/* ------------------------------------------------------------------ */
/* Graph rendering                                                     */
/* ------------------------------------------------------------------ */

const NODE_STYLES: Record<string, string> = {
  start: 'border-emerald-500/70 bg-emerald-950/60 text-emerald-200',
  end: 'border-indigo-500/70 bg-indigo-950/60 text-indigo-200',
  gateway: 'border-amber-500/70 bg-amber-950/60 text-amber-200',
  activity: 'border-violet-500/60 bg-violet-950/40 text-violet-100',
};

function buildFlowElements(graph: GraphPayload) {
  const nodes: any[] = [];
  const edges: any[] = [];

  const ordered = [
    ...graph.events.filter((e) => e.type === 'start'),
    ...graph.activities,
    ...graph.gateways,
    ...graph.events.filter((e) => e.type !== 'start'),
  ];

  ordered.forEach((node, index) => {
    const isEvent = 'type' in node && !('label' in node && 'actor_id' in node && 'temporal_order' in node);
    const label = 'question' in node ? node.question : (node as any).label;
    const kind =
      'type' in node && !('actor_id' in node && 'temporal_order' in node)
        ? (node as ProcessEvent).type
        : 'question' in node
          ? 'gateway'
          : 'activity';

    nodes.push({
      id: node.id,
      position: { x: 220 + (index % 3) * 280, y: 40 + Math.floor(index / 3) * 130 },
      data: {
        label: (
          <div className="px-1 py-0.5 text-[11px] leading-tight">
            <div className="font-semibold">{label}</div>
            <div className="mt-0.5 font-mono text-[9px] uppercase opacity-60">{kind}</div>
          </div>
        ),
      },
      className: NODE_STYLES[kind] ?? NODE_STYLES.activity,
      style: { borderRadius: 10, borderWidth: 1, fontSize: 11 },
    });
    void isEvent;
  });

  graph.transitions.forEach((t) => {
    edges.push({
      id: t.id || `${t.from_id}->${t.to_id}`,
      source: t.from_id,
      target: t.to_id,
      label: t.condition || t.label || undefined,
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: t.is_loop ? '#f59e0b' : '#8b5cf6', strokeWidth: 1.5 },
      labelStyle: { fill: '#a1a1aa', fontSize: 10 },
      labelBgStyle: { fill: '#18181b' },
    });
  });

  return { nodes, edges };
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

type TabId = 'graph' | 'flowchart' | 'swimlane' | 'state' | 'bpmn' | 'defects' | 'ast';

export const ProcessGraphStudioPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const presetFileId = searchParams.get('file_id');

  const { data: files } = useApiData<FileRecord[]>('/api/files');

  const [sourceType, setSourceType] = useState<'existing' | 'upload'>(presetFileId ? 'existing' : 'upload');
  const [fileId, setFileId] = useState(presetFileId ?? '');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [result, setResult] = useState<GraphResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>('graph');

  const runPipeline = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const form = new FormData();
      if (sourceType === 'existing') {
        if (!fileId) throw new Error('Select a document to run the pipeline against.');
        form.append('file_id', fileId);
      } else {
        if (!uploadFile) throw new Error('Choose a source document to upload.');
        form.append('file', uploadFile);
      }
      const payload = await api.upload<GraphResponse>('/api/v1/process-graph/generate', form);
      setResult(payload);
      setTab('graph');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Process graph generation failed.');
    } finally {
      setRunning(false);
    }
  }, [sourceType, fileId, uploadFile]);

  const flow = useMemo(() => (result ? buildFlowElements(result.graph) : null), [result]);

  const tabs: { id: TabId; label: React.ReactNode; count?: number }[] = [
    { id: 'graph', label: 'Canonical Graph' },
    { id: 'flowchart', label: 'Mermaid Flowchart' },
    { id: 'swimlane', label: 'Mermaid Swimlane' },
    { id: 'state', label: 'State Machine' },
    { id: 'bpmn', label: 'BPMN 2.0 XML' },
    {
      id: 'defects',
      label: 'Defect Register',
      count: result?.defect_register.defects.length ?? 0,
    },
    { id: 'ast', label: 'Canonical AST JSON' },
  ];

  return (
    <div>
      <PageHeader
        title="Process Graph Studio"
        description="Evidence-first procedural extraction with System-1 verification. Only claims grounded in the source enter the authoritative graph; everything else is quarantined into the defect register."
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_1fr]">
        {/* Source configuration */}
        <div className="space-y-4">
          <Panel title="Source Document">
            <div className="space-y-3">
              <div className="flex gap-1.5">
                {(['existing', 'upload'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setSourceType(mode)}
                    className={cn(
                      'flex-1 rounded-lg border px-2 py-1.5 text-[11px] font-medium capitalize transition',
                      sourceType === mode
                        ? 'border-violet-500 bg-violet-950/50 text-violet-200'
                        : 'border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800'
                    )}
                  >
                    {mode === 'existing' ? 'Existing' : 'Upload'}
                  </button>
                ))}
              </div>

              {sourceType === 'existing' ? (
                <Field label="Indexed document">
                  <select value={fileId} onChange={(e) => setFileId(e.target.value)} className={selectClass}>
                    <option value="">Select a document…</option>
                    {(files ?? []).map((file) => (
                      <option key={file.id} value={file.id}>
                        {file.name}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <Field label="Source file" hint="PDF, DOCX, TXT and Markdown are supported.">
                  <input
                    type="file"
                    accept=".pdf,.docx,.txt,.md,.pptx,.xlsx,.csv"
                    onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs text-zinc-300 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-800 file:px-2.5 file:py-1 file:text-[11px] file:text-zinc-200"
                  />
                </Field>
              )}

              <Button variant="primary" className="w-full" disabled={running} onClick={() => void runPipeline()}>
                {running ? (
                  <div className="h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                {running ? 'Running Pipeline…' : 'Run Process Graph Pipeline'}
              </Button>

              {error && (
                <Alert tone="rose">
                  <span className="flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>{error}</span>
                  </span>
                </Alert>
              )}
            </div>
          </Panel>

          {result && (
            <>
              <Panel title="Run Metrics">
                <div className="grid grid-cols-2 gap-2">
                  <StatCard label="Activities" value={result.metrics.activities_count} tone="violet" />
                  <StatCard label="Gateways" value={result.metrics.gateways_count} tone="amber" />
                  <StatCard label="Transitions" value={result.metrics.transitions_count} tone="sky" />
                  <StatCard label="Actors" value={result.metrics.actors_count} tone="indigo" />
                </div>
              </Panel>

              <Panel title="Latency">
                <dl className="space-y-1.5 text-[11px]">
                  <div className="flex justify-between">
                    <dt className="text-zinc-500">Extraction</dt>
                    <dd className="font-mono text-zinc-300">{result.latencies.extraction_sec.toFixed(2)}s</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-500">System-1 Verification</dt>
                    <dd className="font-mono text-zinc-300">{result.latencies.laya_sec.toFixed(2)}s</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-500">Compilation</dt>
                    <dd className="font-mono text-zinc-300">{result.latencies.compilation_sec.toFixed(2)}s</dd>
                  </div>
                  <div className="flex justify-between border-t border-zinc-800 pt-1.5">
                    <dt className="text-zinc-500">Total</dt>
                    <dd className="font-mono text-emerald-300">{result.latencies.total_sec.toFixed(2)}s</dd>
                  </div>
                </dl>
              </Panel>
            </>
          )}
        </div>

        {/* Studio */}
        <Panel
          title={result ? result.process_name : 'Process Graph Studio'}
          subtitle={result?.objective ?? 'No graph generated yet.'}
          bodyClassName="p-0"
          action={
            result ? (
              <div className="flex items-center gap-1.5">
                <Button
                  onClick={() => downloadText(`${result.document_name}_bpmn_2_0.bpmn`, result.bpmn_2_0_xml, 'application/xml')}
                >
                  <Download className="h-3.5 w-3.5" />
                  .bpmn
                </Button>
                <Button
                  onClick={() =>
                    downloadText(`${result.document_name}_flowchart.mmd`, result.flowchart_mermaid, 'text/plain')
                  }
                >
                  <Download className="h-3.5 w-3.5" />
                  .mmd
                </Button>
              </div>
            ) : null
          }
        >
          {!result ? (
            <div className="p-4">
              <EmptyState
                icon={<Workflow className="h-7 w-7" />}
                title="No Process Graph Loaded"
                description="Select a source document and run the evidence-first pipeline to compile a verified process graph."
              />
            </div>
          ) : (
            <>
              <TabBar tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} className="px-2" />

              <div className="p-4">
                {tab === 'graph' && (
                  <div className="h-[62vh] overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/60">
                    {flow && (
                      <ReactFlow
                        nodes={flow.nodes}
                        edges={flow.edges}
                        fitView
                        minZoom={0.15}
                        maxZoom={2}
                        proOptions={{ hideAttribution: true }}
                      >
                        <Background color="#27272a" gap={16} />
                        <Controls />
                      </ReactFlow>
                    )}
                  </div>
                )}

                {tab === 'flowchart' && (
                  <CodeBlock content={result.flowchart_mermaid} empty="// No Mermaid flowchart generated" />
                )}
                {tab === 'swimlane' && (
                  <CodeBlock content={result.swimlane_mermaid} empty="// No Mermaid swimlane generated" />
                )}
                {tab === 'state' && (
                  <CodeBlock
                    content={result.state_machine_mermaid}
                    empty="// No state machine transitions in this graph"
                  />
                )}
                {tab === 'bpmn' && <CodeBlock content={result.bpmn_2_0_xml} tone="violet" empty="<!-- No BPMN XML -->" />}
                {tab === 'ast' && (
                  <CodeBlock content={JSON.stringify(result.graph, null, 2)} tone="violet" />
                )}

                {tab === 'defects' && <DefectTable register={result.defect_register} />}
              </div>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Defect register                                                     */
/* ------------------------------------------------------------------ */

const DefectTable: React.FC<{ register: DefectRegister }> = ({ register }) => {
  if (!register.defects.length) {
    return (
      <EmptyState
        icon={<Boxes className="h-7 w-7" />}
        title="Zero Quarantine Defects"
        description="Every proposition was strictly entailed by the source evidence."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatCard label="Extracted" value={register.total_propositions_extracted} />
        <StatCard label="Supported" value={register.propositions_supported} tone="emerald" />
        <StatCard label="Uncertain" value={register.propositions_uncertain} tone="amber" />
        <StatCard label="Unsupported" value={register.propositions_unsupported} tone="rose" />
      </div>

      <Table>
        <thead>
          <tr>
            <Th>#</Th>
            <Th>Category</Th>
            <Th>Quarantined Claim</Th>
            <Th>Cited Spans</Th>
            <Th>Evidence</Th>
            <Th>Rationale</Th>
            <Th>Confidence</Th>
          </tr>
        </thead>
        <tbody>
          {register.defects.map((defect, index) => (
            <tr key={defect.proposition_id} className="hover:bg-zinc-900/40">
              <Td className="font-mono text-zinc-600">{index + 1}</Td>
              <Td>
                <Badge tone="amber" mono>
                  {String(defect.defect_category).replace(/_/g, ' ')}
                </Badge>
              </Td>
              <Td className="max-w-xs text-zinc-200">{defect.claimed_statement}</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  {defect.evidence_spans.map((span) => (
                    <Badge key={span} tone="violet" mono>
                      {span}
                    </Badge>
                  ))}
                </div>
              </Td>
              <Td className="max-w-xs text-[11px] text-zinc-500">
                {defect.evidence_text?.slice(0, 90)}
                {defect.evidence_text?.length > 90 ? '…' : ''}
              </Td>
              <Td className="max-w-xs text-[11px] text-rose-300/80">{defect.rationale}</Td>
              <Td className="font-mono text-zinc-400">{defect.confidence?.toFixed(2)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
};

export default ProcessGraphStudioPage;
