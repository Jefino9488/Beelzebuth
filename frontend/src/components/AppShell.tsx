/**
 * Application shell.
 * Provides the persistent sidebar navigation, the header with tenant scope / identity,
 * and the routed content area. This replaces the server-rendered Jinja console layout.
 */

import React, { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Zap,
  LayoutDashboard,
  FileText,
  Workflow,
  BookOpen,
  ShieldAlert,
  Building2,
  ScrollText,
  Settings,
  Cpu,
  Radar,
} from 'lucide-react';
import { useProfile } from '../lib/useProfile';
import { cn, Badge, Loading } from './ui';

const NAV_ITEMS = [
  { to: '/workbench', label: 'Workbench', icon: Radar },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/documents', label: 'Documents', icon: FileText },
  { to: '/process-graph', label: 'Process Graph', icon: Workflow },
  { to: '/defects', label: 'Defect Register', icon: ShieldAlert },
  { to: '/admin', label: 'Tenants', icon: Building2 },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export const AppShell: React.FC = () => {
  const { profile } = useProfile();

  const roleTone =
    profile?.role === 'SUPER_ADMIN' ? 'violet' : profile?.role === 'CLIENT_ADMIN' ? 'sky' : 'neutral';

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100">
      {/* Sidebar */}
      <aside className="flex w-[220px] shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950">
        <div className="flex h-14 items-center gap-2 border-b border-zinc-800/80 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-indigo-500">
            <Zap className="h-3.5 w-3.5 text-white" />
          </div>
          <div className="leading-tight">
            <div className="text-xs font-bold tracking-tight text-zinc-100">Injester</div>
            <div className="text-[9px] uppercase tracking-wider text-zinc-600">Evidence Engine</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs font-medium transition',
                  isActive
                    ? 'bg-violet-950/50 text-violet-200 border border-violet-800/50'
                    : 'text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300 border border-transparent'
                )
              }
            >
              <item.icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-zinc-800/80 p-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-[11px] font-bold text-zinc-200">
              {profile?.email ? profile.email[0].toUpperCase() : '?'}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11px] font-medium text-zinc-200">
                {profile?.email ?? 'Platform'}
              </div>
              <Badge tone={roleTone} className="mt-0.5">
                {profile?.role?.replace('_', ' ') ?? 'LOCAL'}
              </Badge>
            </div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/80 px-5 backdrop-blur-md">
          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <Cpu className="h-3.5 w-3.5 text-violet-400" />
            <span>Universal Document Digest &amp; Diagram Engine</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="emerald">Zero Synthetic Drift</Badge>
            <Badge tone="violet">BYOAI</Badge>
          </div>
        </header>

        <main className="scrollable-pane min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <Suspense fallback={<Loading label="Loading view…" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
};
