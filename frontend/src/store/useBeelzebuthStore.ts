import { create } from 'zustand';
import { apiRequest } from '../lib/api';
import { DocumentDigest, InquisitorVerification } from '../types';

export const EMPTY_DOC: DocumentDigest = {
  id: '',
  filename: 'No Document Loaded',
  file_hash: '',
  file_type: 'NONE',
  page_count: 0,
  raw_tokens: 0,
  clean_tokens: 0,
  compression_ratio: 0,
  raw_content: 'No document loaded yet. Drop a document (.pdf, .docx, .txt, .md) above to devour into readable markdown and diagrams.',
  spans: [],
  process_graph: { nodes: [], edges: [] },
  extracted_schema: {},
  digital_markdown: '# No Document Loaded\n\nDrop a document (.pdf, .docx, .txt, .md) above to devour into readable markdown and diagrams.',
  defects: [],
};

interface BeelzebuthState {
  currentDoc: DocumentDigest;
  activeTab: 'markdown' | 'workflow' | 'llm' | 'schema';
  activeSpanId: string | null;
  hoveredSpanId: string | null;
  isDevouring: boolean;
  devourProgress: string;
  isDefectDrawerOpen: boolean;
  isSettingsOpen: boolean;
  inquisitorQuery: string;
  inquisitorResult: InquisitorVerification | null;
  isInquisitorRunning: boolean;
  availableSamples: Array<{ id: string; filename: string; title: string; file_type: string }>;
  devourAbortController: AbortController | null;
  inquisitorAbortController: AbortController | null;

  // Actions
  setActiveTab: (tab: 'markdown' | 'workflow' | 'llm' | 'schema') => void;
  setActiveSpanId: (spanId: string | null) => void;
  setHoveredSpanId: (spanId: string | null) => void;
  toggleDefectDrawer: () => void;
  toggleSettings: () => void;
  fetchSamples: () => Promise<void>;
  loadSampleDoc: (id: string) => Promise<void>;
  devourFile: (file: File) => Promise<void>;
  abortDevour: () => void;
  runInquisitor: (query: string) => Promise<void>;
  abortInquisitor: () => void;
  updateMarkdown: (md: string) => void;
}

export const useBeelzebuthStore = create<BeelzebuthState>((set, get) => ({
  currentDoc: EMPTY_DOC,
  activeTab: 'markdown',
  activeSpanId: null,
  hoveredSpanId: null,
  isDevouring: false,
  devourProgress: '',
  isDefectDrawerOpen: false,
  isSettingsOpen: false,
  inquisitorQuery: '',
  inquisitorResult: null,
  isInquisitorRunning: false,
  availableSamples: [],
  devourAbortController: null,
  inquisitorAbortController: null,

  setActiveTab: (tab) => set({ activeTab: tab }),
  setActiveSpanId: (spanId) => set({ activeSpanId: spanId }),
  setHoveredSpanId: (spanId) => set({ hoveredSpanId: spanId }),
  toggleDefectDrawer: () => set((state) => ({ isDefectDrawerOpen: !state.isDefectDrawerOpen })),
  toggleSettings: () => set((state) => ({ isSettingsOpen: !state.isSettingsOpen })),
  updateMarkdown: (md: string) => {
    const doc = get().currentDoc;
    set({ currentDoc: { ...doc, digital_markdown: md } });
  },

  fetchSamples: async () => {
    try {
      const samples = await apiRequest<any[]>('/api/v1/beelzebuth/samples');
      set({ availableSamples: samples });
      // If no document is loaded yet and samples exist, load the first real sample
      if (get().currentDoc.id === '' && samples.length > 0) {
        get().loadSampleDoc(samples[0].id);
      }
    } catch (err) {
      console.warn('Failed to fetch real samples:', err);
    }
  },

  loadSampleDoc: async (id) => {
    try {
      const samples = await apiRequest<any[]>('/api/v1/beelzebuth/samples');
      {
        const found = samples.find((s: any) => s.id === id || s.filename.includes(id));
        if (found) {
          set({
            currentDoc: {
              id: found.id,
              filename: found.filename,
              file_hash: found.file_hash,
              file_type: found.file_type,
              page_count: found.page_count,
              raw_tokens: found.raw_tokens,
              clean_tokens: found.clean_tokens,
              compression_ratio: found.compression_ratio,
              raw_content: found.raw_content,
              spans: found.spans || [],
              process_graph: found.process_graph || { nodes: [], edges: [] },
              extracted_schema: found.extracted_schema || {},
              digital_markdown: found.digital_markdown || found.raw_content,
              defects: found.defects || [],
            },
            activeSpanId: null,
            hoveredSpanId: null,
            inquisitorResult: null,
          });
          return;
        }
      }
    } catch (err) {
      console.warn('Could not fetch sample document from server:', err);
    }
  },

  devourFile: async (file: File) => {
    // If a previous devour is active, abort it
    const prevController = get().devourAbortController;
    if (prevController) {
      prevController.abort();
    }

    const controller = new AbortController();
    let elapsedSeconds = 0;

    set({
      isDevouring: true,
      devourProgress: `Devouring ${file.name} (0s)...`,
      devourAbortController: controller,
    });

    const timer = setInterval(() => {
      elapsedSeconds += 1;
      let phase = '';
      if (elapsedSeconds < 2) {
        phase = 'Segmenting granular evidence spans';
      } else if (elapsedSeconds < 5) {
        phase = 'Reconstructing digital Markdown (.md), tables & diagrams';
      } else {
        phase = 'Finalizing citation-grounded Markdown document';
      }
      set({ devourProgress: `${phase} (${elapsedSeconds}s elapsed)...` });
    }, 1000);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const data = await apiRequest<any>('/api/v1/beelzebuth/devour', {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });

      clearInterval(timer);
      set({
        currentDoc: {
          ...data,
          digital_markdown: data.digital_markdown || data.raw_content || '',
        },
        activeTab: 'markdown',
        isDevouring: false,
        devourProgress: '',
        devourAbortController: null,
      });
      return;
    } catch (err: any) {
      clearInterval(timer);
      if (err.name === 'AbortError') {
        set({
          isDevouring: false,
          devourProgress: 'Devour operation cancelled by user.',
          devourAbortController: null,
        });
        return;
      }
      console.error('API devour failed:', err);
      const errMsg = err?.message || 'Server error';
      set({
        isDevouring: false,
        devourProgress: `Devour failed (${elapsedSeconds}s): ${errMsg}. Check terminal logs.`,
        devourAbortController: null,
      });
    }
  },

  abortDevour: () => {
    const controller = get().devourAbortController;
    if (controller) {
      controller.abort();
    }
    set({
      isDevouring: false,
      devourProgress: 'Processing stopped by user.',
      devourAbortController: null,
    });
  },

  runInquisitor: async (query: string) => {
    if (!query.trim()) return;

    const prevController = get().inquisitorAbortController;
    if (prevController) {
      prevController.abort();
    }

    const controller = new AbortController();
    set({
      isInquisitorRunning: true,
      inquisitorQuery: query,
      inquisitorAbortController: controller,
    });

    const { currentDoc, activeSpanId } = get();
    if (!currentDoc.spans || currentDoc.spans.length === 0) {
      set({
        isInquisitorRunning: false,
        inquisitorResult: {
          hypothesis: query,
          verdict: 'UNCERTAIN',
          confidence: 0,
          justification: 'No active evidence spans available in the current document.',
          cited_spans: [],
        },
        inquisitorAbortController: null,
      });
      return;
    }

    const queryLower = query.toLowerCase();
    const matchedSpan =
      (activeSpanId && currentDoc.spans.find((s) => s.id === activeSpanId)) ||
      currentDoc.spans.find((s) =>
        queryLower.split(' ').some((w) => w.length > 4 && s.text.toLowerCase().includes(w))
      ) ||
      currentDoc.spans[0];

    try {
      const data = await apiRequest<any>('/api/v1/beelzebuth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hypothesis: query,
          span_text: matchedSpan.text,
          span_id: matchedSpan.id,
        }),
        signal: controller.signal,
      });

      {
        set({
          inquisitorResult: {
            hypothesis: data.hypothesis,
            verdict: data.verdict as any,
            confidence: data.confidence,
            justification: data.justification,
            cited_spans: data.cited_spans,
          },
          isInquisitorRunning: false,
          activeSpanId: matchedSpan.id,
          inquisitorAbortController: null,
        });
        return;
      }
    } catch (e: any) {
      if (e.name === 'AbortError') {
        set({
          isInquisitorRunning: false,
          inquisitorAbortController: null,
        });
        return;
      }
      console.warn('Real NLI API call failed:', e);
    }

    set({
      isInquisitorRunning: false,
      inquisitorResult: {
        hypothesis: query,
        verdict: 'UNCERTAIN',
        confidence: 0,
        justification: 'Unable to reach the NLI verification service. Ensure backend server is running.',
        cited_spans: [matchedSpan.id],
      },
      activeSpanId: matchedSpan.id,
      inquisitorAbortController: null,
    });
  },

  abortInquisitor: () => {
    const controller = get().inquisitorAbortController;
    if (controller) {
      controller.abort();
    }
    set({
      isInquisitorRunning: false,
      inquisitorAbortController: null,
    });
  },
}));
