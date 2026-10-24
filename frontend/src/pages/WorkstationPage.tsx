import React from 'react';
import { Header } from '../components/Header';
import { DevourDropzone } from '../components/DevourDropzone';
import { SourceViewer } from '../components/SourceViewer';
import { LLMContextTab } from '../components/tabs/LLMContextTab';
import { WorkflowTab } from '../components/tabs/WorkflowTab';
import { SchemaTab } from '../components/tabs/SchemaTab';
import { DigitalMarkdownTab } from '../components/tabs/DigitalMarkdownTab';
import { InquisitorBar } from '../components/InquisitorBar';
import { DefectDrawer } from '../components/DefectDrawer';
import { SettingsModal } from '../components/SettingsModal';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';
import { Sparkles, Workflow, Database, FileText } from 'lucide-react';

/**
 * Evidence Workbench.
 *
 * The single-document workstation: a dropzone for ingestion, the immutable
 * source grounding plane, and a tabbed transmutation studio that projects the
 * document into Digital Markdown (.md), diagram views, LLM context, and schema views.
 */

export function WorkstationPage() {
  const { activeTab, setActiveTab } = useBeelzebuthStore();

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-zinc-950 font-sans text-zinc-100 select-none">
      {/* 1. Top Global Navigation Header */}
      <Header />

      {/* 2. Main Workstation Area */}
      <div className="flex-1 flex flex-col p-3 gap-3 overflow-hidden min-h-0">
        {/* Top Dropzone */}
        <div className="shrink-0">
          <DevourDropzone />
        </div>

        {/* Dual-Pane Studio */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-3 min-h-0">
          {/* Left Pane: Source Document Grounding */}
          <div className="h-full min-h-0">
            <SourceViewer />
          </div>

          {/* Right Pane: Transmutation Studio */}
          <div className="h-full min-h-0 flex flex-col bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl">
            {/* Tab Selector Bar */}
            <div className="p-2 border-b border-zinc-800 bg-zinc-900/50 flex items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-1">
                {/* 1. Digital Markdown (.md) - Primary Deliverable */}
                <button
                  onClick={() => setActiveTab('markdown')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    activeTab === 'markdown' || activeTab === 'sop'
                      ? 'bg-violet-600 text-white shadow-md shadow-violet-950/50'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`}
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Digital Markdown (.md)</span>
                </button>

                {/* 2. Diagram View */}
                <button
                  onClick={() => setActiveTab('workflow')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    activeTab === 'workflow'
                      ? 'bg-violet-600 text-white shadow-md shadow-violet-950/50'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`}
                >
                  <Workflow className="w-3.5 h-3.5" />
                  <span>Diagram View</span>
                </button>

                {/* 3. LLM Context */}
                <button
                  onClick={() => setActiveTab('llm')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    activeTab === 'llm'
                      ? 'bg-violet-600 text-white shadow-md shadow-violet-950/50'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`}
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>LLM Context</span>
                </button>

                {/* 4. Schema (JSON) */}
                <button
                  onClick={() => setActiveTab('schema')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    activeTab === 'schema'
                      ? 'bg-violet-600 text-white shadow-md shadow-violet-950/50'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`}
                >
                  <Database className="w-3.5 h-3.5" />
                  <span>Schema (JSON)</span>
                </button>
              </div>

              <div className="hidden sm:flex items-center gap-2 text-[10px] text-zinc-500 font-mono">
                <span>DIGITAL TARGETS</span>
              </div>
            </div>

            {/* Active Tab Content */}
            <div className="flex-1 min-h-0">
              {(activeTab === 'markdown' || activeTab === 'sop') && <DigitalMarkdownTab />}
              {activeTab === 'workflow' && <WorkflowTab />}
              {activeTab === 'llm' && <LLMContextTab />}
              {activeTab === 'schema' && <SchemaTab />}
            </div>
          </div>
        </div>
      </div>

      {/* 3. Bottom Inquisitor NLI Verification Bar */}
      <div className="shrink-0">
        <InquisitorBar />
      </div>

      {/* 4. Collapsible Hallucination Firewall & Defect Drawer */}
      <DefectDrawer />

      {/* 5. BYOAI Settings Modal */}
      <SettingsModal />
    </div>
  );
}

export default WorkstationPage;
