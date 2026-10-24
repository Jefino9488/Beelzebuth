import React from 'react';
import { ShieldAlert, AlertTriangle, X, ChevronUp, ChevronDown, CheckCircle2, ShieldCheck } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';

export const DefectDrawer: React.FC = () => {
  const { currentDoc, isDefectDrawerOpen, toggleDefectDrawer, setActiveSpanId } = useBeelzebuthStore();

  if (!isDefectDrawerOpen) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 bg-zinc-950/95 border-t border-rose-900/60 shadow-2xl backdrop-blur-xl transition-all max-h-[40vh] flex flex-col">
      {/* Drawer Header */}
      <div className="p-3 px-4 bg-zinc-900/80 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-rose-400" />
          <span className="text-xs font-semibold text-zinc-100">Hallucination Firewall & Defect Register</span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60">
            {currentDoc.defects.length} Quarantined Items
          </span>
        </div>

        <button
          onClick={toggleDefectDrawer}
          className="p-1 rounded-md text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Defect Items List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2.5 scrollable-pane">
        {currentDoc.defects.map((defect) => (
          <div
            key={defect.id}
            className="p-3 rounded-lg bg-zinc-900/60 border border-rose-900/40 hover:border-rose-700/60 transition text-xs"
          >
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded font-mono text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800/80">
                  {defect.type}
                </span>
                <span className="text-zinc-400 text-[11px]">Target: <span className="font-mono text-zinc-200">{defect.element_id}</span></span>
              </div>

              <div className="flex items-center gap-2">
                <span
                  className={`text-[10px] uppercase font-bold px-1.5 py-0.2 rounded ${
                    defect.severity === 'HIGH'
                      ? 'bg-rose-900 text-rose-200'
                      : defect.severity === 'MEDIUM'
                      ? 'bg-amber-900 text-amber-200'
                      : 'bg-zinc-800 text-zinc-300'
                  }`}
                >
                  {defect.severity} Severity
                </span>

                {defect.cited_spans.map((spanId) => (
                  <button
                    key={spanId}
                    onClick={() => setActiveSpanId(spanId)}
                    className="px-1.5 py-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 font-mono text-[10px] hover:bg-violet-900 transition"
                  >
                    [{spanId}]
                  </button>
                ))}
              </div>
            </div>

            <p className="text-zinc-300 leading-relaxed mb-1.5">{defect.description}</p>

            {defect.recommended_fix && (
              <div className="text-[11px] text-emerald-400/90 font-mono bg-emerald-950/30 p-1.5 px-2 rounded border border-emerald-900/40">
                Fix: {defect.recommended_fix}
              </div>
            )}
          </div>
        ))}

        {currentDoc.defects.length === 0 && (
          <div className="py-8 text-center text-zinc-400 flex flex-col items-center justify-center gap-2">
            <ShieldCheck className="w-8 h-8 text-emerald-400" />
            <span className="text-xs font-medium text-zinc-200">Zero Hallucinations Detected</span>
            <span className="text-[11px] text-zinc-500">All claims and transitions are 100% strictly entailed by source evidence spans.</span>
          </div>
        )}
      </div>
    </div>
  );
};
