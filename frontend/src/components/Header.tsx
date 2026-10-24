import React, { useEffect } from 'react';
import { Zap, ShieldAlert, FileText, ChevronDown, CheckCircle2, ArrowRight, Settings } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';

export const Header: React.FC = () => {
  const { currentDoc, availableSamples, fetchSamples, loadSampleDoc, toggleDefectDrawer, toggleSettings } = useBeelzebuthStore();

  useEffect(() => {
    fetchSamples();
  }, [fetchSamples]);

  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md px-4 flex items-center justify-between sticky top-0 z-40 select-none">
      {/* Brand & Project Identity */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-violet-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-violet-900/40">
          <Zap className="w-5 h-5 text-white fill-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold tracking-tight text-white text-base">BEELZEBUTH</span>
            <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded bg-violet-950/80 text-violet-300 border border-violet-800/60">
              Grounded Engine
            </span>
          </div>
        </div>
      </div>

      {/* Middle: Document Switcher & Compression Telemetry */}
      <div className="hidden md:flex items-center gap-4">
        {/* Document Selector */}
        <div className="relative group">
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-200 hover:border-zinc-700 transition">
            <FileText className="w-3.5 h-3.5 text-violet-400" />
            <span className="font-medium max-w-[200px] truncate">{currentDoc.filename}</span>
            <ChevronDown className="w-3 h-3 text-zinc-400" />
          </button>

          <div className="absolute top-full left-0 mt-1 w-72 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl p-1.5 hidden group-hover:block z-50">
            <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider px-2 py-1">
              Available Documents
            </div>
            {availableSamples.length === 0 ? (
              <div className="px-2 py-2 text-xs text-zinc-500 italic">No stored documents found. Drop a file to devour.</div>
            ) : (
              availableSamples.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => loadSampleDoc(doc.id)}
                  className={`w-full text-left px-2 py-1.5 rounded text-xs flex items-center justify-between ${
                    currentDoc.id === doc.id
                      ? 'bg-violet-900/30 text-violet-200 font-medium'
                      : 'text-zinc-300 hover:bg-zinc-800/80'
                  }`}
                >
                  <span className="truncate">{doc.filename}</span>
                  <span className="text-[10px] text-zinc-500 uppercase">{doc.file_type}</span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Compression & Telemetry Pill */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-zinc-900/80 border border-zinc-800 text-xs">
          <span className="text-zinc-400">Tokens:</span>
          <span className="text-zinc-500 line-through text-[11px]">{(currentDoc.raw_tokens || 0).toLocaleString()}</span>
          <ArrowRight className="w-3 h-3 text-zinc-600" />
          <span className="text-emerald-400 font-semibold text-[11px]">{(currentDoc.clean_tokens || 0).toLocaleString()}</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/80 text-emerald-400 font-bold border border-emerald-800/40">
            -{Math.round((currentDoc.compression_ratio || 0) * 100)}%
          </span>
        </div>

        {/* Verification Status */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-900/80 border border-zinc-800 text-xs">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-zinc-300 text-[11px] font-medium">NLI Grounded</span>
        </div>
      </div>

      {/* Right Actions */}
      <div className="flex items-center gap-2">
        {/* Settings / BYOAI Modal Toggle Button */}
        <button
          onClick={toggleSettings}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border bg-zinc-900 hover:bg-zinc-800 border-zinc-800 text-zinc-300 hover:text-white transition"
          title="Configure LLM Providers & API Keys"
        >
          <Settings className="w-3.5 h-3.5 text-violet-400" />
          <span className="hidden sm:inline">Settings</span>
        </button>

        {/* Defect Drawer Toggle Button */}
        <button
          onClick={toggleDefectDrawer}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition ${
            (currentDoc.defects || []).length > 0
              ? 'bg-rose-950/40 text-rose-300 border-rose-800/50 hover:bg-rose-900/40'
              : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:text-zinc-200'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
          <span>Defects ({(currentDoc.defects || []).length})</span>
        </button>

        {/* GitHub link */}
        <a
          href="https://github.com/Jefino9488/Beelzebuth"
          target="_blank"
          rel="noreferrer"
          className="p-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 transition"
          title="View on GitHub"
        >
          <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
            <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
          </svg>
        </a>
      </div>
    </header>
  );
};
