import React, { useState } from 'react';
import { Database, Copy, Check, CheckCircle2, AlertTriangle, Braces, Sliders, ExternalLink } from 'lucide-react';
import { useBeelzebuthStore } from '../../store/useBeelzebuthStore';

export const SchemaTab: React.FC = () => {
  const { currentDoc, setActiveSpanId, setHoveredSpanId } = useBeelzebuthStore();
  const [viewFormat, setViewFormat] = useState<'structured' | 'json'>('structured');
  const [copied, setCopied] = useState(false);

  const fields = Object.values(currentDoc.extracted_schema || {});

  const handleCopyJson = () => {
    const jsonObj: Record<string, any> = {};
    fields.forEach((f) => {
      jsonObj[f.key] = f.value;
    });
    navigator.clipboard.writeText(JSON.stringify(jsonObj, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl">
      {/* Top Header */}
      <div className="p-3 border-b border-zinc-800 bg-zinc-900/40 flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs">
            <Database className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-zinc-300 font-medium">Universal Structured Extractor</span>
          </div>

          <div className="flex items-center gap-1 bg-zinc-900 p-0.5 rounded-lg border border-zinc-800 text-[11px]">
            <button
              onClick={() => setViewFormat('structured')}
              className={`px-2 py-0.5 rounded ${viewFormat === 'structured' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Verified Fields
            </button>
            <button
              onClick={() => setViewFormat('json')}
              className={`px-2 py-0.5 rounded ${viewFormat === 'json' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Raw JSON
            </button>
          </div>
        </div>

        <button
          onClick={handleCopyJson}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-300 transition"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? 'Copied JSON' : 'Copy JSON'}</span>
        </button>
      </div>

      {/* Main Content Area */}
      {viewFormat === 'structured' ? (
        <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollable-pane">
          {fields.map((field) => (
            <div
              key={field.key}
              className="p-3 rounded-lg border border-zinc-800/80 bg-zinc-900/40 hover:border-zinc-700 transition"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-zinc-200">{field.key}</span>
                  <span className="text-[10px] font-mono uppercase px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                    {field.type}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1 text-[10px] font-medium text-emerald-400 px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800/50">
                    <CheckCircle2 className="w-3 h-3" />
                    <span>{Math.round(field.confidence * 100)}% Entailed</span>
                  </div>

                  {field.cited_spans.map((spanId) => (
                    <button
                      key={spanId}
                      onClick={() => setActiveSpanId(spanId)}
                      onMouseEnter={() => setHoveredSpanId(spanId)}
                      onMouseLeave={() => setHoveredSpanId(null)}
                      className="px-1.5 py-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 text-[10px] font-mono hover:bg-violet-900 transition"
                    >
                      [{spanId}]
                    </button>
                  ))}
                </div>
              </div>

              <div className="p-2.5 rounded bg-zinc-950 border border-zinc-800/60 font-mono text-xs text-zinc-300 overflow-x-auto">
                {Array.isArray(field.value) ? (
                  <div className="flex flex-wrap gap-1.5">
                    {field.value.map((v, i) => (
                      <span key={i} className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-violet-300 text-[11px]">
                        "{v}"
                      </span>
                    ))}
                  </div>
                ) : typeof field.value === 'object' ? (
                  JSON.stringify(field.value, null, 2)
                ) : (
                  <span>{String(field.value)}</span>
                )}
              </div>
            </div>
          ))}

          {fields.length === 0 && (
            <div className="py-12 text-center text-zinc-500 text-xs">
              No schema fields extracted from this document.
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 font-mono text-xs text-violet-300 bg-zinc-950 whitespace-pre scrollable-pane select-text">
          {JSON.stringify(
            fields.reduce((acc, f) => ({ ...acc, [f.key]: f.value }), {}),
            null,
            2
          )}
        </div>
      )}
    </div>
  );
};
