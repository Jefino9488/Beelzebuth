import React, { useState } from 'react';
import { Copy, Check, Terminal, Sparkles, SlidersHorizontal, ArrowDownRight } from 'lucide-react';
import { useBeelzebuthStore } from '../../store/useBeelzebuthStore';

export const LLMContextTab: React.FC = () => {
  const { currentDoc } = useBeelzebuthStore();
  const [copied, setCopied] = useState(false);
  const [includeSpans, setIncludeSpans] = useState(true);
  const [promptTemplate, setPromptTemplate] = useState<'standard' | 'system' | 'json'>('standard');

  const getExportContent = () => {
    let content = currentDoc.raw_content;
    if (!includeSpans) {
      content = content.replace(/\[S\d{3,4}\]/g, '');
    }

    if (promptTemplate === 'system') {
      return `You are an accurate, evidence-bound assistant. You must answer questions using ONLY the following verified document context. If an answer cannot be entailed from the context, state that you do not have sufficient information.\n\n<DOCUMENT_CONTEXT filename="${currentDoc.filename}" sha256="${currentDoc.file_hash}">\n${content}\n</DOCUMENT_CONTEXT>`;
    }
    if (promptTemplate === 'json') {
      return `Extract structured data from the document below according to the provided schema. Every field value must be strictly entailed by the document context.\n\n${content}`;
    }
    return content;
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(getExportContent());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl">
      {/* Top Controls */}
      <div className="p-3 border-b border-zinc-800 bg-zinc-900/40 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs">
            <Sparkles className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-zinc-300 font-medium">LLM-Optimized Clean Context</span>
          </div>

          {/* Template Selector */}
          <div className="flex items-center gap-1 bg-zinc-900 p-0.5 rounded-lg border border-zinc-800 text-[11px]">
            <button
              onClick={() => setPromptTemplate('standard')}
              className={`px-2 py-0.5 rounded ${promptTemplate === 'standard' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Standard
            </button>
            <button
              onClick={() => setPromptTemplate('system')}
              className={`px-2 py-0.5 rounded ${promptTemplate === 'system' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              System Prompt
            </button>
            <button
              onClick={() => setPromptTemplate('json')}
              className={`px-2 py-0.5 rounded ${promptTemplate === 'json' ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              Extraction Prompt
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Toggle Spans */}
          <label className="flex items-center gap-1.5 text-[11px] text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={includeSpans}
              onChange={(e) => setIncludeSpans(e.target.checked)}
              className="rounded bg-zinc-900 border-zinc-700 text-violet-600 focus:ring-0"
            />
            <span>Include [S###] tags</span>
          </label>

          {/* Copy Button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium shadow-md shadow-violet-950/60 transition"
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied to Clipboard' : 'Copy for LLM'}</span>
          </button>
        </div>
      </div>

      {/* Token Efficiency Banner */}
      <div className="px-4 py-2 bg-zinc-900/20 border-b border-zinc-800/60 flex items-center justify-between text-xs text-zinc-400">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-zinc-500" />
          <span>Token budget:</span>
          <span className="font-mono text-zinc-300">{currentDoc.clean_tokens.toLocaleString()} tokens</span>
          <span className="text-zinc-500 font-mono">(compressed from {currentDoc.raw_tokens.toLocaleString()})</span>
        </div>
        <div className="font-mono text-[11px] text-emerald-400">
          Saved ~{currentDoc.raw_tokens - currentDoc.clean_tokens} tokens ({Math.round(currentDoc.compression_ratio * 100)}%)
        </div>
      </div>

      {/* Editor / Text Preview */}
      <div className="flex-1 overflow-y-auto p-4 scrollable-pane font-mono text-xs text-zinc-300 bg-zinc-950/80 leading-relaxed whitespace-pre-wrap select-text">
        {getExportContent()}
      </div>
    </div>
  );
};
