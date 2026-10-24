import React, { useEffect, useRef, useState } from 'react';
import { FileText, Search, Tag, Eye, Hash, ExternalLink, Bookmark } from 'lucide-react';
import { useBeelzebuthStore } from '../store/useBeelzebuthStore';

export const SourceViewer: React.FC = () => {
  const { currentDoc, activeSpanId, hoveredSpanId, setActiveSpanId, setHoveredSpanId } = useBeelzebuthStore();
  const [searchTerm, setSearchTerm] = useState('');
  const spanRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Auto-scroll to active span when it changes
  useEffect(() => {
    if (activeSpanId && spanRefs.current[activeSpanId]) {
      spanRefs.current[activeSpanId]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [activeSpanId]);

  const filteredSpans = currentDoc.spans.filter(
    (s) =>
      s.text.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (s.section && s.section.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl">
      {/* Viewer Header */}
      <div className="p-3 border-b border-zinc-800 bg-zinc-900/40 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-zinc-800/80 text-violet-400">
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
              <span>Source Grounding Plane</span>
              <span className="text-[10px] text-zinc-400 font-mono">({currentDoc.spans.length} spans)</span>
            </div>
            <div className="text-[10px] text-zinc-500 font-mono truncate max-w-[240px]">
              SHA-256: {currentDoc.file_hash.substring(0, 16)}...
            </div>
          </div>
        </div>

        {/* Search Spans */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search spans..."
            className="pl-8 pr-2 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-[11px] text-zinc-200 placeholder-zinc-500 w-36 focus:outline-none focus:border-violet-500"
          />
        </div>
      </div>

      {/* Main Document Content with Span Highlights */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollable-pane text-xs leading-relaxed text-zinc-300">
        {filteredSpans.map((span) => {
          const isActive = activeSpanId === span.id;
          const isHovered = hoveredSpanId === span.id;

          return (
            <div
              key={span.id}
              ref={(el) => { spanRefs.current[span.id] = el; }}
              onMouseEnter={() => setHoveredSpanId(span.id)}
              onMouseLeave={() => setHoveredSpanId(null)}
              onClick={() => setActiveSpanId(span.id)}
              className={`p-3 rounded-lg border transition-all cursor-pointer relative group ${
                isActive
                  ? 'bg-violet-950/40 border-violet-500/80 shadow-md shadow-violet-950/50 ring-1 ring-violet-500/40'
                  : isHovered
                  ? 'bg-zinc-900/90 border-violet-800/60'
                  : 'bg-zinc-900/40 border-zinc-800/60 hover:border-zinc-700'
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                      isActive || isHovered
                        ? 'bg-violet-600 text-white border-violet-400'
                        : 'bg-zinc-800 text-violet-400 border-zinc-700'
                    }`}
                  >
                    [{span.id}]
                  </span>
                  {span.section && (
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">
                      § {span.section}
                    </span>
                  )}
                </div>

                {span.page && (
                  <span className="text-[10px] text-zinc-500 font-mono">
                    Page {span.page}
                  </span>
                )}
              </div>

              <p className="text-zinc-200 font-normal leading-normal">{span.text}</p>
            </div>
          );
        })}

        {filteredSpans.length === 0 && (
          <div className="py-12 text-center text-zinc-500 text-xs">
            No source spans match "{searchTerm}"
          </div>
        )}
      </div>

      {/* Footer Grounding Guarantee */}
      <div className="p-2 px-3 border-t border-zinc-800/80 bg-zinc-950 text-[10px] text-zinc-500 flex items-center justify-between font-mono">
        <span>IMMUTABLE EVIDENCE PLANE</span>
        <span>ZERO SYNTHETIC DRIFT</span>
      </div>
    </div>
  );
};
