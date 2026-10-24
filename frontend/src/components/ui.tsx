/**
 * Shared UI primitives.
 * Small, unopinionated building blocks that keep every console page visually consistent
 * with the existing dark "zinc + violet" design language.
 */

import React from 'react';

export const cn = (...classes: (string | false | null | undefined)[]) =>
  classes.filter(Boolean).join(' ');

/* ------------------------------------------------------------------ */
/* Surfaces                                                            */
/* ------------------------------------------------------------------ */

export function Panel({
  title,
  subtitle,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn('rounded-xl border border-zinc-800/80 bg-zinc-900/40', className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-zinc-800/80 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[11px] text-zinc-400">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={cn('p-4', bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-bold tracking-tight text-zinc-100">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-xs text-zinc-400">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Badges & pills                                                      */
/* ------------------------------------------------------------------ */

type Tone = 'neutral' | 'violet' | 'emerald' | 'amber' | 'rose' | 'indigo' | 'sky';

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-zinc-800/80 text-zinc-300 border-zinc-700',
  violet: 'bg-violet-950/60 text-violet-300 border-violet-800/60',
  emerald: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/60',
  amber: 'bg-amber-950/60 text-amber-300 border-amber-800/60',
  rose: 'bg-rose-950/60 text-rose-300 border-rose-800/60',
  indigo: 'bg-indigo-950/60 text-indigo-300 border-indigo-800/60',
  sky: 'bg-sky-950/60 text-sky-300 border-sky-800/60',
};

export function Badge({
  children,
  tone = 'neutral',
  className,
  mono = false,
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
  mono?: boolean;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium',
        mono && 'font-mono',
        TONE_CLASSES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Buttons                                                             */
/* ------------------------------------------------------------------ */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white shadow-lg shadow-violet-950/40',
  secondary: 'bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300',
  ghost: 'hover:bg-zinc-800/70 text-zinc-400 hover:text-zinc-200',
  danger: 'bg-rose-950/60 hover:bg-rose-900/60 border border-rose-800/60 text-rose-300',
};

export function Button({
  children,
  variant = 'secondary',
  className,
  disabled,
  onClick,
  type = 'button',
  title,
}: {
  children: React.ReactNode;
  variant?: ButtonVariant;
  className?: string;
  disabled?: boolean;
  onClick?: () => void;
  type?: 'button' | 'submit';
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        BUTTON_VARIANTS[variant],
        className
      )}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Form controls                                                       */
/* ------------------------------------------------------------------ */

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('space-y-1', className)}>
      {label && <label className="block text-[11px] font-medium text-zinc-300">{label}</label>}
      {children}
      {hint && <p className="text-[10px] text-zinc-500">{hint}</p>}
    </div>
  );
}

export const inputClass =
  'w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none transition';

export const selectClass =
  'w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none transition';

/* ------------------------------------------------------------------ */
/* Tables                                                              */
/* ------------------------------------------------------------------ */

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-x-auto rounded-lg border border-zinc-800/80', className)}>
      <table className="w-full border-collapse text-left text-xs">{children}</table>
    </div>
  );
}

export function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        'border-b border-zinc-800 bg-zinc-900/60 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500',
        className
      )}
    >
      {children}
    </th>
  );
}

export function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={cn('border-b border-zinc-800/50 px-3 py-2 align-top text-zinc-300', className)}>
      {children}
    </td>
  );
}

/* ------------------------------------------------------------------ */
/* States                                                              */
/* ------------------------------------------------------------------ */

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-800 px-6 py-12 text-center">
      {icon && <div className="text-zinc-600">{icon}</div>}
      <p className="text-sm font-semibold text-zinc-300">{title}</p>
      {description && <p className="max-w-md text-xs text-zinc-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Alert({ tone = 'rose', children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <div className={cn('rounded-lg border px-3 py-2 text-xs', TONE_CLASSES[tone])}>{children}</div>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-xs text-zinc-500">
      <div className="h-3.5 w-3.5 rounded-full border-2 border-zinc-600 border-t-transparent animate-spin" />
      <span>{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tabs                                                                */
/* ------------------------------------------------------------------ */

export function TabBar({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: { id: string; label: React.ReactNode; count?: number }[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-wrap items-center gap-1 border-b border-zinc-800', className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            'relative flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition',
            active === tab.id
              ? 'text-violet-200 after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:rounded-full after:bg-violet-500'
              : 'text-zinc-500 hover:text-zinc-300'
          )}
        >
          {tab.label}
          {typeof tab.count === 'number' && (
            <span
              className={cn(
                'rounded px-1 py-0.5 text-[9px] font-mono',
                active === tab.id ? 'bg-violet-950/70 text-violet-300' : 'bg-zinc-800/70 text-zinc-400'
              )}
            >
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */

export function CodeBlock({
  content,
  tone = 'emerald',
  className,
  empty = '// No content available',
}: {
  content?: string | null;
  tone?: 'emerald' | 'violet';
  className?: string;
  empty?: string;
}) {
  const text = content && content.trim() ? content : empty;
  return (
    <pre
      className={cn(
        'scrollable-pane max-h-[60vh] overflow-auto whitespace-pre rounded-lg border border-zinc-800 bg-zinc-950/70 p-3 font-mono text-[11px] leading-relaxed',
        tone === 'emerald' ? 'text-emerald-300' : 'text-violet-300',
        className
      )}
    >
      {text}
    </pre>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={cn('mt-1.5 text-2xl font-bold tracking-tight', {
        neutral: 'text-zinc-100',
        violet: 'text-violet-300',
        emerald: 'text-emerald-300',
        amber: 'text-amber-300',
        rose: 'text-rose-300',
        indigo: 'text-indigo-300',
        sky: 'text-sky-300',
      }[tone])}>
        {value}
      </div>
      {hint && <div className="mt-1 text-[10px] text-zinc-500">{hint}</div>}
    </div>
  );
}

export function downloadText(filename: string, content: string, mimeType = 'text/plain') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
