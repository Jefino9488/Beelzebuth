import React, { useState } from 'react';
import { FileText, Copy, Check, ShieldCheck, Download, Edit3, Eye } from 'lucide-react';
import { useBeelzebuthStore } from '../../store/useBeelzebuthStore';

export const DigitalMarkdownTab: React.FC = () => {
  const { currentDoc, setActiveSpanId, setHoveredSpanId, updateMarkdown } = useBeelzebuthStore();
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const markdownContent = currentDoc.digital_markdown || currentDoc.sop_markdown || '';

  const handleCopy = () => {
    navigator.clipboard.writeText(markdownContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const filename = `${(currentDoc.filename || 'document').replace(/\.[^/.]+$/, '')}.md`;
    const blob = new Blob([markdownContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  // Render markdown text replacing [S###] with clickable interactive buttons
  const renderInteractiveMarkdown = (content: string) => {
    const lines = content.split('\n');
    return lines.map((line, idx) => {
      // Empty line
      if (!line.trim()) {
        return <div key={idx} className="h-2" />;
      }

      // Headers
      if (line.startsWith('# ')) {
        return <h1 key={idx} className="text-lg font-bold text-zinc-100 mt-4 mb-2">{line.replace('# ', '')}</h1>;
      }
      if (line.startsWith('## ')) {
        return <h2 key={idx} className="text-sm font-semibold text-violet-300 mt-3 mb-1.5">{line.replace('## ', '')}</h2>;
      }
      if (line.startsWith('### ')) {
        return <h3 key={idx} className="text-xs font-semibold text-zinc-200 mt-2 mb-1">{line.replace('### ', '')}</h3>;
      }

      // Table row (GFM table)
      if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
        return (
          <div key={idx} className="font-mono text-[11px] text-zinc-300 overflow-x-auto whitespace-pre bg-zinc-900/50 px-2 py-0.5 rounded border border-zinc-800/50 my-0.5">
            {line}
          </div>
        );
      }

      // Bullet lists
      if (line.startsWith('- ') || line.startsWith('* ')) {
        const bulletContent = line.substring(2);
        const parts = bulletContent.split(/(\[S\d{3,4}\])/g);
        return (
          <div key={idx} className="flex items-start gap-2 text-xs text-zinc-300 my-1 leading-relaxed pl-2">
            <span className="text-violet-400 font-bold">•</span>
            <div>
              {parts.map((part, pIdx) => {
                const match = part.match(/\[(S\d{3,4})\]/);
                if (match) {
                  const spanId = match[1];
                  return (
                    <button
                      key={pIdx}
                      onClick={() => setActiveSpanId(spanId)}
                      onMouseEnter={() => setHoveredSpanId(spanId)}
                      onMouseLeave={() => setHoveredSpanId(null)}
                      className="inline-flex items-center px-1.5 py-0.2 mx-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 font-mono text-[10px] hover:bg-violet-900 transition cursor-pointer"
                    >
                      [{spanId}]
                    </button>
                  );
                }
                return <span key={pIdx}>{part}</span>;
              })}
            </div>
          </div>
        );
      }

      // Parse [S###] in general lines
      const parts = line.split(/(\[S\d{3,4}\])/g);
      return (
        <p key={idx} className="text-xs text-zinc-300 my-1 leading-relaxed">
          {parts.map((part, pIdx) => {
            const match = part.match(/\[(S\d{3,4})\]/);
            if (match) {
              const spanId = match[1];
              return (
                <button
                  key={pIdx}
                  onClick={() => setActiveSpanId(spanId)}
                  onMouseEnter={() => setHoveredSpanId(spanId)}
                  onMouseLeave={() => setHoveredSpanId(null)}
                  className="inline-flex items-center px-1.5 py-0.2 mx-0.5 rounded bg-violet-950 border border-violet-800 text-violet-300 font-mono text-[10px] hover:bg-violet-900 transition cursor-pointer"
                >
                  [{spanId}]
                </button>
              );
            }
            return <span key={pIdx}>{part}</span>;
          })}
        </p>
      );
    });
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-xl border border-zinc-800/80 overflow-hidden shadow-xl">
      {/* Top Header */}
      <div className="p-3 border-b border-zinc-800 bg-zinc-900/40 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs">
            <FileText className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-zinc-300 font-medium">Digital Markdown (.md)</span>
          </div>

          {/* Mode Switcher: Read vs Edit */}
          <div className="flex items-center gap-1 bg-zinc-900 p-0.5 rounded-lg border border-zinc-800 text-[11px]">
            <button
              onClick={() => setIsEditing(false)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded transition cursor-pointer ${!isEditing ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              <Eye className="w-3 h-3" />
              <span>Read</span>
            </button>
            <button
              onClick={() => setIsEditing(true)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded transition cursor-pointer ${isEditing ? 'bg-violet-950 text-violet-300 font-medium' : 'text-zinc-400 hover:text-zinc-200'}`}
            >
              <Edit3 className="w-3 h-3" />
              <span>Edit (.md)</span>
            </button>
          </div>

          <div className="hidden sm:flex items-center gap-1 text-[11px] font-mono text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/40 border border-emerald-800/40">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Citation Grounded</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Download .md button */}
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-300 transition cursor-pointer"
            title="Download digitized .md file"
          >
            <Download className="w-3.5 h-3.5 text-violet-400" />
            <span className="hidden sm:inline">Download</span> .md
          </button>

          {/* Copy Markdown button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-300 transition cursor-pointer"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>
      </div>

      {/* Content Area */}
      {isEditing ? (
        <div className="flex-1 flex flex-col p-3 bg-zinc-950 overflow-hidden">
          <div className="flex items-center justify-between pb-2 text-[11px] text-zinc-500 font-mono">
            <span>EDITABLE DIGITAL MARKDOWN (.md)</span>
            <span>{markdownContent.length} chars • {markdownContent.split('\n').length} lines</span>
          </div>
          <textarea
            value={markdownContent}
            onChange={(e) => updateMarkdown(e.target.value)}
            className="flex-1 w-full bg-zinc-900/70 border border-zinc-800 focus:border-violet-600 rounded-lg p-3 font-mono text-xs text-zinc-200 focus:outline-none resize-none leading-relaxed select-text shadow-inner"
            placeholder="Type or edit markdown here..."
            spellCheck={false}
          />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 scrollable-pane space-y-2">
          {renderInteractiveMarkdown(markdownContent)}
        </div>
      )}
    </div>
  );
};
export default DigitalMarkdownTab;
