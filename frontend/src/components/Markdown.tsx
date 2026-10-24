/**
 * Markdown renderer.
 *
 * Uses `marked` for parsing and `dompurify` for sanitisation, because the rendered
 * content originates from LLM output over user-supplied documents and must never be
 * able to inject scripts. Citation markers ([S###] / [C##]) are additionally turned into
 * interactive chips when an `onCitation` handler is supplied.
 */

import React, { useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ gfm: true, breaks: false });

export interface MarkdownProps {
  content?: string | null;
  onCitation?: (tag: string) => void;
  className?: string;
}

const CITATION_PATTERN = /(\[S\d{2,4}\]|\[C\d{2,4}\])/g;

export const Markdown: React.FC<MarkdownProps> = ({ content, onCitation, className }) => {
  const html = useMemo(() => {
    if (!content) return '';
    const parsed = marked.parse(content) as string;
    return DOMPurify.sanitize(parsed, {
      ADD_ATTR: ['target', 'rel'],
      FORBID_TAGS: ['style', 'form', 'input', 'button'],
    });
  }, [content]);

  const interactive = useMemo(() => {
    if (!onCitation) return html;
    // Replace citation markers with anchor tags *after* sanitisation so the injected
    // markup is exactly what we authored (no user-controlled attributes).
    return html.replace(CITATION_PATTERN, (match) => {
      const id = match.slice(1, -1);
      return `<a href="#" data-citation="${id}" class="inline-flex items-center rounded border border-violet-700/60 bg-violet-950/50 px-1 py-0.5 font-mono text-[10px] text-violet-300 no-underline">${match}</a>`;
    });
  }, [html, onCitation]);

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onCitation) return;
    const target = (event.target as HTMLElement).closest('a[data-citation]');
    if (!target) return;
    event.preventDefault();
    onCitation(target.getAttribute('data-citation') || '');
  };

  return (
    <div
      className={
        className ??
        'markdown-body select-text text-xs leading-relaxed text-zinc-300 [&_a]:text-violet-300 [&_blockquote]:border-l-2 [&_blockquote]:border-zinc-700 [&_blockquote]:pl-3 [&_blockquote]:text-zinc-400 [&_code]:rounded [&_code]:bg-zinc-800/70 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[11px] [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-base [&_h1]:font-bold [&_h1]:text-zinc-100 [&_h2]:mb-2 [&_h2]:mt-3.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-violet-300 [&_h3]:mb-1.5 [&_h3]:mt-3 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-zinc-200 [&_li]:ml-4 [&_list-disc]:list-disc [&_ol]:list-decimal [&_p]:my-1.5 [&_pre]:overflow-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:border-zinc-800 [&_pre]:bg-zinc-950/70 [&_pre]:p-3 [&_pre]:font-mono [&_pre]:text-[11px] [&_pre]:text-emerald-300 [&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-zinc-800 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-zinc-800 [&_th]:bg-zinc-900/70 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_th]:text-zinc-300'
      }
      onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: interactive }}
    />
  );
};
