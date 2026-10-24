import React from 'react';
import { X, Settings } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';
import { SettingsPanel } from './SettingsPanel';

export const SettingsModal: React.FC = () => {
  const { isSettingsOpen, toggleSettings } = useBeelzebuthStore();

  if (!isSettingsOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm animate-in fade-in duration-150">
      <div
        className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/50 p-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-violet-800/60 bg-violet-950/80 text-violet-300">
              <Settings className="h-4 w-4" />
            </div>
            <div>
              <h2 className="flex items-center gap-2 text-sm font-bold text-zinc-100">
                Engine &amp; BYOAI Settings
                <span className="rounded border border-violet-800/40 bg-violet-950/80 px-2 py-0.5 font-mono text-[10px] text-violet-300">
                  Bring Your Own API
                </span>
              </h2>
              <p className="text-[11px] text-zinc-400">
                Configure your local or cloud LLM provider, the System-1 grounding verifier, and API
                credentials.
              </p>
            </div>
          </div>

          <button
            onClick={toggleSettings}
            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="scrollable-pane flex-1 overflow-y-auto p-5">
          <SettingsPanel compact />
        </div>
      </div>
    </div>
  );
};
