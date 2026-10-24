import React, { useRef } from 'react';
import { UploadCloud, Sparkles, Square, FileUp } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';

export const DevourDropzone: React.FC = () => {
  const { devourFile, isDevouring, devourProgress, abortDevour } = useBeelzebuthStore();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (isDevouring) return;
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      devourFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      devourFile(e.target.files[0]);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={`relative rounded-xl border border-dashed transition text-center group ${
        isDevouring
          ? 'border-violet-700/80 bg-violet-950/20 p-5 cursor-default'
          : 'border-zinc-800 bg-zinc-950/40 hover:bg-zinc-900/40 hover:border-violet-700/50 p-4 cursor-pointer'
      }`}
      onClick={() => {
        if (!isDevouring) fileInputRef.current?.click();
      }}
    >
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.json"
      />

      {isDevouring ? (
        <div className="py-4 flex flex-col items-center justify-center gap-2.5">
          <div className="relative">
            <div className="w-10 h-10 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
            <Sparkles className="w-4 h-4 text-violet-400 absolute inset-0 m-auto animate-pulse" />
          </div>
          <div className="text-xs font-semibold text-violet-300 animate-pulse">{devourProgress}</div>
          <p className="text-[11px] text-zinc-500">Devouring document, segmenting granular spans, preserving tables & diagrams...</p>

          {/* Stop / Abort Button */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              abortDevour();
            }}
            className="mt-1 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950/90 hover:bg-rose-900 border border-rose-800 text-xs text-rose-200 font-semibold transition shadow-lg shadow-rose-950/50 cursor-pointer"
            title="Abort current file ingestion"
          >
            <Square className="w-3.5 h-3.5 fill-rose-400 text-rose-400" />
            <span>Stop Devouring</span>
          </button>
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-3 text-left">
            <div className="w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400 group-hover:text-violet-400 group-hover:border-violet-800/60 transition">
              <UploadCloud className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-semibold text-zinc-200">
                Devour any document into Markdown (.md) <span className="text-zinc-500 font-normal">(PDF, DOCX, TXT, MD, CSV)</span>
              </div>
              <div className="text-[11px] text-zinc-400">
                Preserves all context, tables, diagrams &amp; creates citation-verified digital Markdown
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium flex items-center gap-1.5 transition shadow-sm"
            >
              <FileUp className="w-3.5 h-3.5" />
              <span>Choose Document</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
