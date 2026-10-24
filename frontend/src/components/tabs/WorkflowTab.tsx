import React, { useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Workflow, Code, FileCode, CheckCircle2, AlertTriangle, ShieldCheck, Download, ArrowRight } from 'lucide-react';
import { useBeelzebuthStore } from '../../store/useBeelzebuthStore';

export const WorkflowTab: React.FC = () => {
  const { currentDoc, setActiveSpanId, setHoveredSpanId } = useBeelzebuthStore();
  const [viewMode, setViewMode] = useState<'visual' | 'bpmn' | 'mermaid'>('visual');
  const [selectedEdge, setSelectedEdge] = useState<any | null>(null);

  // Convert currentDoc process_graph nodes to ReactFlow nodes
  const nodes: Node[] = useMemo(() => {
    return currentDoc.process_graph.nodes.map((node, index) => {
      // Automatic staggered layout
      const x = 200 + (index % 2) * 260;
      const y = 50 + index * 100;

      let bgColor = 'bg-zinc-900 border-zinc-700';
      let iconColor = 'text-zinc-400';

      if (node.type === 'start') {
        bgColor = 'bg-emerald-950/40 border-emerald-600/80 text-emerald-200';
        iconColor = 'text-emerald-400';
      } else if (node.type === 'end') {
        bgColor = 'bg-indigo-950/40 border-indigo-600/80 text-indigo-200';
        iconColor = 'text-indigo-400';
      } else if (node.type === 'gateway') {
        bgColor = 'bg-amber-950/40 border-amber-600/80 text-amber-200';
        iconColor = 'text-amber-400';
      }

      return {
        id: node.id,
        position: { x, y },
        data: {
          label: (
            <div
              className={`p-3 rounded-lg border text-left shadow-lg transition hover:scale-105 cursor-pointer ${bgColor}`}
              onClick={() => node.cited_spans[0] && setActiveSpanId(node.cited_spans[0])}
              onMouseEnter={() => node.cited_spans[0] && setHoveredSpanId(node.cited_spans[0])}
              onMouseLeave={() => setHoveredSpanId(null)}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                  {node.role || node.type}
                </span>
                <div className="flex items-center gap-1">
                  {node.cited_spans.map((s) => (
                    <span key={s} className="text-[9px] font-mono px-1 py-0.2 rounded bg-zinc-800 text-violet-300 border border-zinc-700">
                      [{s}]
                    </span>
                  ))}
                </div>
              </div>
              <div className="text-xs font-semibold leading-snug">{node.label}</div>
            </div>
          ),
        },
        type: 'default',
      };
    });
  }, [currentDoc.process_graph.nodes, setActiveSpanId, setHoveredSpanId]);

  // Convert currentDoc process_graph edges to ReactFlow edges
  const edges: Edge[] = useMemo(() => {
    return currentDoc.process_graph.edges.map((edge) => {
      const isAmbiguous = edge.status === 'AMBIGUOUS';
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.condition || '',
        animated: edge.status === 'VERIFIED',
        style: {
          stroke: isAmbiguous ? '#f43f5e' : '#8b5cf6',
          strokeWidth: 2,
        },
        labelStyle: {
          fill: '#d4d4d8',
          fontSize: 10,
          fontWeight: 500,
        },
        labelBgStyle: {
          fill: '#18181b',
          fillOpacity: 0.9,
          rx: 4,
          stroke: '#27272a',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isAmbiguous ? '#f43f5e' : '#8b5cf6',
        },
      };
    });
  }, [currentDoc.process_graph.edges]);

  const onEdgeClick = (_: any, edge: Edge) => {
    const rawEdge = currentDoc.process_graph.edges.find((e) => e.id === edge.id);
    if (rawEdge) {
      setSelectedEdge(rawEdge);
      if (rawEdge.cited_spans[0]) {
        setActiveSpanId(rawEdge.cited_spans[0]);
      }
    }
  };

  const handleDownload = () => {
    const content = viewMode === 'bpmn' ? currentDoc.process_graph.bpmn_xml : currentDoc.process_graph.mermaid_code;
    const blob = new Blob([content || ''], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${currentDoc.filename.replace(/\.[^/.]+$/, '')}.${viewMode === 'bpmn' ? 'bpmn' : 'mmd'}`;
    a.click();
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl relative">
      {/* Tab Header Controls */}
      <div className="p-3 border-b border-zinc-800 bg-zinc-900/40 flex items-center justify-between gap-2 z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs">
            <Workflow className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-zinc-300 font-medium">Canonical Process Model</span>
          </div>

          {/* View Toggles */}
          <div className="flex items-center gap-1 bg-zinc-900 p-0.5 rounded-lg border border-zinc-800 text-[11px]">
            <button
              onClick={() => setViewMode('visual')}
              className={`px-2 py-0.5 rounded ${viewMode === 'visual' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Interactive Canvas
            </button>
            <button
              onClick={() => setViewMode('mermaid')}
              className={`px-2 py-0.5 rounded ${viewMode === 'mermaid' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Mermaid
            </button>
            <button
              onClick={() => setViewMode('bpmn')}
              className={`px-2 py-0.5 rounded ${viewMode === 'bpmn' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              BPMN 2.0 XML
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {viewMode !== 'visual' && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-300 transition"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download {viewMode.toUpperCase()}</span>
            </button>
          )}

          <div className="flex items-center gap-1 text-[11px] font-mono text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/40 border border-emerald-800/40">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>MultiDiGraph Verified</span>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 relative overflow-hidden bg-zinc-950">
        {viewMode === 'visual' && (
          <div className="w-full h-full">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onEdgeClick={onEdgeClick}
              fitView
              minZoom={0.2}
              maxZoom={2}
            >
              <Background color="#27272a" gap={16} />
              <Controls className="bg-zinc-900 border-zinc-800 text-zinc-300 fill-zinc-300" />
            </ReactFlow>

            {/* Edge Detail Drawer */}
            {selectedEdge && (
              <div className="absolute bottom-4 left-4 right-4 bg-zinc-900/95 border border-zinc-700/80 rounded-xl p-3 shadow-2xl backdrop-blur-md flex items-center justify-between gap-4 z-20">
                <div>
                  <div className="text-[10px] uppercase font-bold text-violet-400 flex items-center gap-1.5 mb-0.5">
                    <span>Transition Edge [{selectedEdge.id}]</span>
                    <span className="text-zinc-500">•</span>
                    <span className="text-emerald-400">NLI Confidence: {Math.round(selectedEdge.confidence * 100)}%</span>
                  </div>
                  <div className="text-xs text-zinc-200 font-medium">
                    Condition: <span className="text-violet-300 font-mono">"{selectedEdge.condition}"</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-zinc-400">Evidence Spans:</span>
                  {selectedEdge.cited_spans.map((spanId: string) => (
                    <button
                      key={spanId}
                      onClick={() => setActiveSpanId(spanId)}
                      className="px-2 py-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 text-xs font-mono hover:bg-violet-900 transition"
                    >
                      [{spanId}]
                    </button>
                  ))}
                  <button
                    onClick={() => setSelectedEdge(null)}
                    className="ml-2 text-zinc-500 hover:text-zinc-300 text-xs font-mono"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {viewMode === 'mermaid' && (
          <div className="w-full h-full p-4 overflow-y-auto font-mono text-xs text-emerald-400 bg-zinc-950 whitespace-pre scrollable-pane select-text">
            {currentDoc.process_graph.mermaid_code || '// No Mermaid code generated'}
          </div>
        )}

        {viewMode === 'bpmn' && (
          <div className="w-full h-full p-4 overflow-y-auto font-mono text-xs text-violet-300 bg-zinc-950 whitespace-pre scrollable-pane select-text">
            {currentDoc.process_graph.bpmn_xml || '<!-- No BPMN XML available -->'}
          </div>
        )}
      </div>
    </div>
  );
};
