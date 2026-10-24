import React, { useState } from 'react';
import { Search, Sparkles, ShieldAlert, ArrowRight, CheckCircle2, AlertTriangle, Square } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';

export const InquisitorBar: React.FC = () => {
  const { runInquisitor, abortInquisitor, isInquisitorRunning, inquisitorResult, setActiveSpanId } = useBeelzebuthStore();
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !isInquisitorRunning) {
      runInquisitor(query.trim());
    }
  };

  return (
    <div className="border-t border-zinc-800 bg-zinc-950/90 backdrop-blur-md p-3 px-4 flex flex-col gap-2">
      {/* Search Input Bar */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <div className="relative flex-1">
          <Sparkles className="w-4 h-4 text-violet-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Inquisitor: Test any claim or question against document evidence with System-1 NLI..."
            className="w-full pl-9 pr-4 py-2 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition"
          />
        </div>

        {isInquisitorRunning ? (
          <button
            type="button"
            onClick={abortInquisitor}
            className="px-3.5 py-2 rounded-lg bg-rose-950/90 hover:bg-rose-900 border border-rose-800 text-rose-200 text-xs font-semibold flex items-center gap-1.5 shadow-lg shadow-rose-950/50 transition cursor-pointer"
            title="Stop verification"
          >
            <Square className="w-3.5 h-3.5 fill-rose-400 text-rose-400" />
            <span>Stop</span>
          </button>
        ) : (
          <button
            type="submit"
            disabled={!query.trim()}
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50 text-white text-xs font-medium flex items-center gap-1.5 shadow-lg shadow-violet-950/50 transition"
          >
            <ArrowRight className="w-4 h-4" />
            <span>Verify Claim</span>
          </button>
        )}
      </form>

      {/* Result Card if available */}
      {inquisitorResult && (
        <div className="p-3 rounded-lg bg-zinc-900/90 border border-zinc-700/80 text-xs flex items-start justify-between gap-4 animate-in fade-in duration-200">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span
                className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold border flex items-center gap-1 ${
                  inquisitorResult.verdict === 'ENTAILED'
                    ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                    : inquisitorResult.verdict === 'CONTRADICTED'
                    ? 'bg-rose-950 text-rose-300 border-rose-800'
                    : 'bg-amber-950 text-amber-300 border-amber-800'
                }`}
              >
                {inquisitorResult.verdict === 'ENTAILED' && <CheckCircle2 className="w-3 h-3" />}
                {inquisitorResult.verdict === 'CONTRADICTED' && <ShieldAlert className="w-3 h-3" />}
                {inquisitorResult.verdict === 'UNCERTAIN' && <AlertTriangle className="w-3 h-3" />}
                <span>{inquisitorResult.verdict} ({Math.round(inquisitorResult.confidence * 100)}%)</span>
              </span>

              <span className="text-zinc-400 text-[11px] font-medium">
                "{inquisitorResult.hypothesis}"
              </span>
            </div>

            <p className="text-zinc-300 text-[11px] leading-relaxed">
              {inquisitorResult.justification}
            </p>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[10px] text-zinc-400">Cited Evidence:</span>
            {inquisitorResult.cited_spans.map((spanId) => (
              <button
                key={spanId}
                onClick={() => setActiveSpanId(spanId)}
                className="px-2 py-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 font-mono text-xs hover:bg-violet-900 transition"
              >
                [{spanId}]
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
