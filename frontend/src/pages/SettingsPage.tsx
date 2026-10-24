/**
 * Settings page.
 * Replaces the Jinja `settings.html` template: identity context plus the full BYOAI
 * engine configuration surface.
 */

import React from 'react';
import { useProfile } from '../lib/useProfile';
import { SettingsPanel } from '../components/SettingsPanel';
import { PageHeader, Panel, Badge } from '../components/ui';

export const SettingsPage: React.FC = () => {
  const { profile } = useProfile();

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Your authenticated security context and the Bring Your Own AI configuration for both the reasoning LLM and the System-1 grounding verifier."
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_1fr]">
        <Panel title="Security Context">
          <div className="flex items-center gap-3 border-b border-zinc-800 pb-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-800 text-sm font-bold text-zinc-200">
              {profile?.email ? profile.email[0].toUpperCase() : '?'}
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold text-zinc-100">{profile?.email ?? 'Platform'}</div>
              <div className="text-[10px] text-zinc-500">Authenticated Security Context</div>
            </div>
          </div>

          <dl className="mt-4 space-y-3 text-xs">
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Role</dt>
              <dd className="mt-0.5 text-zinc-200">
                <Badge tone={profile?.role === 'SUPER_ADMIN' ? 'violet' : 'sky'}>
                  {profile?.role?.replace('_', ' ') ?? 'LOCAL'}
                </Badge>
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                Organisation Scope
              </dt>
              <dd className="mt-0.5 text-zinc-200">{profile?.organisation_id ?? 'Platform'}</dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                API Documentation
              </dt>
              <dd className="mt-0.5">
                <a
                  href="/docs"
                  target="_blank"
                  rel="noreferrer"
                  className="text-violet-300 transition hover:text-violet-200"
                >
                  Open Swagger UI (/docs) ↗
                </a>
              </dd>
            </div>
          </dl>
        </Panel>

        <Panel title="Engine & BYOAI Configuration">
          <SettingsPanel />
        </Panel>
      </div>
    </div>
  );
};

export default SettingsPage;
