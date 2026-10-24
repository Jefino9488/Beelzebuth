/**
 * Engine & BYOAI settings panel.
 *
 * Shared by the header settings modal and the dedicated Settings page so that the
 * configuration surface exists in exactly one place.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Server, Check, Eye, EyeOff, Save, RefreshCw, Search, Cpu, ListFilter } from 'lucide-react';
import { api } from '../lib/api';
import { Button, Field, inputClass, selectClass, Badge } from './ui';

interface PresetInfo {
  name: string;
  description: string;
  base_url?: string;
  model?: string;
  free_model?: string;
  needs_gemini_key?: boolean;
}

interface ModelDescriptor {
  id: string;
  name: string;
  provider: string;
  context_length?: number | null;
  is_free: boolean;
  description: string;
}

interface SettingsPayload {
  model_name: string;
  openai_base_url: string;
  openai_api_key_masked: string;
  gemini_api_key_configured: boolean;
  gemini_api_key_masked: string;
  system1_provider: string;
  system1_api_mode: string;
  system1_api_base_url: string;
  system1_api_key_masked: string;
  system1_api_key_configured: boolean;
  system1_model: string;
  embedding_model: string;
  workspace_dir: string;
  database_url: string;
  presets: Record<string, PresetInfo>;
}

const SYSTEM1_PROVIDERS = [
  { value: 'openjev', label: 'OpenJev (Local GPU)' },
  { value: 'laya', label: 'Laya (Local Checkpoint)' },
  { value: 'jev', label: 'TypeSafe Jev (API)' },
  { value: 'openai', label: 'OpenAI-Compatible (API)' },
];

export const SettingsPanel: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const [showApiKey, setShowApiKey] = useState(false);
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showSystem1Key, setShowSystem1Key] = useState(false);

  const [selectedPreset, setSelectedPreset] = useState<string>('custom');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelName, setModelName] = useState('');
  const [geminiApiKey, setGeminiApiKey] = useState('');

  const [system1Provider, setSystem1Provider] = useState('openjev');
  const [system1ApiMode, setSystem1ApiMode] = useState('typesafe');
  const [system1BaseUrl, setSystem1BaseUrl] = useState('');
  const [system1ApiKey, setSystem1ApiKey] = useState('');
  const [system1Model, setSystem1Model] = useState('');

  const [catalogProvider, setCatalogProvider] = useState('openrouter');
  const [freeOnly, setFreeOnly] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [discoveredModels, setDiscoveredModels] = useState<ModelDescriptor[]>([]);
  const [discoveryNote, setDiscoveryNote] = useState('');

  const [workspaceDir, setWorkspaceDir] = useState('');
  const [databaseUrl, setDatabaseUrl] = useState('');
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [presets, setPresets] = useState<Record<string, PresetInfo>>({});

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setErrorMsg('');
    try {
      const data = await api.get<SettingsPayload>('/api/v1/settings');
      setBaseUrl(data.openai_base_url || '');
      setModelName(data.model_name || '');
      setWorkspaceDir(data.workspace_dir || '');
      setDatabaseUrl(data.database_url || '');
      setEmbeddingModel(data.embedding_model || '');
      setPresets(data.presets || {});
      setSystem1Provider(data.system1_provider || 'openjev');
      setSystem1ApiMode(data.system1_api_mode || 'typesafe');
      setSystem1BaseUrl(data.system1_api_base_url || '');
      setSystem1Model(data.system1_model || '');
      setCatalogProvider(
        (data.openai_base_url || '').includes('openrouter.ai') ? 'openrouter' : 'openai_compatible'
      );

      if (data.openai_base_url.includes('openrouter.ai')) {
        setSelectedPreset('openrouter');
      } else if (data.openai_base_url.includes('localhost:11434')) {
        setSelectedPreset('ollama');
      } else if (data.openai_base_url.includes('api.openai.com')) {
        setSelectedPreset('openai');
      } else if (data.gemini_api_key_configured) {
        setSelectedPreset('gemini');
      } else {
        setSelectedPreset('custom');
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to load settings from server.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const handleSelectPreset = (presetKey: string) => {
    setSelectedPreset(presetKey);
    const p = presets[presetKey];
    if (p) {
      if (p.base_url) setBaseUrl(p.base_url);
      if (p.model) setModelName(p.model);
      if (presetKey === 'ollama') setApiKey('ollama');
    }
  };

  const handleDiscoverModels = async () => {
    setDiscovering(true);
    setDiscoveryNote('');
    setDiscoveredModels([]);
    try {
      const res = await api.post<{
        models: ModelDescriptor[];
        returned_count: number;
        total_count: number;
        free_count: number;
      }>('/api/v1/settings/models', {
        provider: catalogProvider,
        base_url: baseUrl || null,
        api_key: apiKey || null,
        free_only: freeOnly,
      });
      setDiscoveredModels(res.models || []);
      setDiscoveryNote(
        `${res.returned_count} of ${res.total_count} models shown (${res.free_count} free available).`
      );
    } catch (err) {
      setDiscoveryNote(
        `Discovery failed: ${err instanceof Error ? err.message : 'unknown error'}`
      );
    } finally {
      setDiscovering(false);
    }
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setErrorMsg('');
    setSaveSuccess(false);

    try {
      const payload: Record<string, unknown> = {
        preset: selectedPreset,
        base_url: baseUrl,
        model_name: modelName,
        system1_provider: system1Provider,
        system1_api_mode: system1ApiMode,
        system1_base_url: system1BaseUrl,
        system1_model: system1Model,
      };
      if (apiKey) payload.api_key = apiKey;
      if (geminiApiKey) payload.gemini_api_key = geminiApiKey;
      if (system1ApiKey) payload.system1_api_key = system1ApiKey;

      await api.post('/api/v1/settings', payload);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to save settings.');
    } finally {
      setSaving(false);
    }
  };

  const system1IsApi = system1Provider === 'jev' || system1Provider === 'openai';

  return (
    <form onSubmit={handleSave} className="space-y-5 text-xs">
      {errorMsg && (
        <div className="rounded-lg border border-rose-800/60 bg-rose-950/50 px-3 py-2 text-rose-300">
          {errorMsg}
        </div>
      )}
      {saveSuccess && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/50 px-3 py-2 text-emerald-300">
          <Check className="h-4 w-4 text-emerald-400" />
          <span>Settings applied successfully and saved to local configuration!</span>
        </div>
      )}

      {/* Provider presets */}
      <div>
        <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wider text-zinc-300">
          Provider Presets
        </label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {['gemini', 'openrouter', 'ollama', 'openai', 'lightning'].map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => handleSelectPreset(key)}
              className={`rounded-xl border p-2.5 text-left transition ${
                selectedPreset === key
                  ? 'border-violet-500 bg-violet-950/60 text-violet-100 shadow-md'
                  : 'border-zinc-800 bg-zinc-900 text-zinc-400 hover:border-zinc-700'
              }`}
            >
              <div className="text-xs font-semibold text-zinc-100">
                {key === 'gemini'
                  ? 'Google Gemini'
                  : key === 'openrouter'
                    ? 'OpenRouter'
                    : key === 'ollama'
                      ? 'Local Ollama'
                      : key === 'openai'
                        ? 'OpenAI'
                        : 'Lightning AI'}
              </div>
              <div className="mt-1 text-[10px] text-zinc-400">
                {presets[key]?.description?.slice(0, 34) ?? 'Custom endpoint'}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* LLM configuration */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field
          label="API Base URL"
          hint="Any OpenAI-compatible endpoint (Ollama, vLLM, OpenRouter, Lightning AI, OpenAI)."
        >
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://openrouter.ai/api/v1"
            className={`${inputClass} font-mono`}
          />
        </Field>

        <Field label="Model Name">
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            list="discovered-models"
            placeholder="e.g. google/gemini-2.5-flash-lite-preview-06-17"
            className={`${inputClass} font-mono`}
          />
          <datalist id="discovered-models">
            {discoveredModels.map((m) => (
              <option key={m.id} value={m.id} />
            ))}
          </datalist>
        </Field>

        <Field label="OpenAI / BYOAI API Key" hint="Leave blank to keep the stored key.">
          <div className="relative">
            <input
              type={showApiKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-or-v1-…, sk-lit-…, or 'ollama'"
              className={`${inputClass} pr-10 font-mono`}
            />
            <button
              type="button"
              onClick={() => setShowApiKey((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 transition hover:text-zinc-200"
            >
              {showApiKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        </Field>

        <Field label="Google Gemini API Key" hint="Optional for the native GenAI SDK.">
          <div className="relative">
            <input
              type={showGeminiKey ? 'text' : 'password'}
              value={geminiApiKey}
              onChange={(e) => setGeminiApiKey(e.target.value)}
              placeholder="AIzaSy…"
              className={`${inputClass} pr-10 font-mono`}
            />
            <button
              type="button"
              onClick={() => setShowGeminiKey((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 transition hover:text-zinc-200"
            >
              {showGeminiKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        </Field>
      </div>

      {/* Model discovery */}
      <div className="space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-300">
          <Search className="h-3.5 w-3.5 text-violet-400" />
          Model Discovery
        </div>
        <p className="text-[10px] text-zinc-500">
          Fetch the live model catalog from your provider and pick the exact identifier to use.
        </p>

        <div className="grid grid-cols-1 items-end gap-2 sm:grid-cols-3">
          <Field label="Catalog Source">
            <select
              value={catalogProvider}
              onChange={(e) => setCatalogProvider(e.target.value)}
              className={selectClass}
            >
              <option value="openrouter">OpenRouter</option>
              <option value="openai_compatible">OpenAI-Compatible</option>
            </select>
          </Field>

          <div className="flex h-[30px] items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={freeOnly}
              onClick={() => setFreeOnly((v) => !v)}
              className={`relative h-5 w-9 rounded-full transition ${freeOnly ? 'bg-violet-600' : 'bg-zinc-700'}`}
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${freeOnly ? 'left-[18px]' : 'left-0.5'}`}
              />
            </button>
            <span className="flex items-center gap-1 text-[11px] text-zinc-300">
              <ListFilter className="h-3 w-3 text-zinc-500" />
              Free models only
            </span>
          </div>

          <Button disabled={discovering} onClick={() => void handleDiscoverModels()}>
            {discovering ? (
              <div className="h-3.5 w-3.5 rounded-full border-2 border-zinc-400 border-t-transparent animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {discovering ? 'Fetching…' : 'Fetch Models'}
          </Button>
        </div>

        {discoveryNote && <p className="font-mono text-[10px] text-zinc-400">{discoveryNote}</p>}

        {discoveredModels.length > 0 && (
          <div className="scrollable-pane max-h-44 divide-y divide-zinc-800/70 overflow-y-auto rounded-lg border border-zinc-800">
            {discoveredModels.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setModelName(m.id)}
                className="flex w-full items-center justify-between gap-3 px-2.5 py-1.5 text-left transition hover:bg-zinc-800/60"
              >
                <span className="truncate font-mono text-[11px] text-zinc-200">{m.id}</span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {m.is_free && (
                    <span className="rounded border border-emerald-800/50 bg-emerald-950/60 px-1.5 py-0.5 font-mono text-[9px] text-emerald-300">
                      FREE
                    </span>
                  )}
                  {m.context_length ? (
                    <span className="font-mono text-[9px] text-zinc-500">
                      {Math.round(m.context_length / 1000)}k
                    </span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* System-1 verifier */}
      <div className="space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-300">
          <Cpu className="h-3.5 w-3.5 text-emerald-400" />
          System-1 Grounding Verifier
        </div>
        <p className="text-[10px] text-zinc-500">
          The System-1 layer decides whether a claim is actually grounded in the source evidence. Local
          engines run offline; API engines follow the same Bring Your Own API contract as the main LLM.
        </p>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Provider">
            <select
              value={system1Provider}
              onChange={(e) => {
                const next = e.target.value;
                setSystem1Provider(next);
                if (next === 'openai') setSystem1ApiMode('openai_compatible');
              }}
              className={selectClass}
            >
              {SYSTEM1_PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>

          {system1IsApi && (
            <Field label="API Mode">
              <select
                value={system1ApiMode}
                onChange={(e) => setSystem1ApiMode(e.target.value)}
                className={selectClass}
              >
                <option value="typesafe">TypeSafe Jev (Noul / Choice)</option>
                <option value="openai_compatible">OpenAI-Compatible</option>
              </select>
            </Field>
          )}
        </div>

        {system1IsApi && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="System-1 API Base URL">
              <input
                type="text"
                value={system1BaseUrl}
                onChange={(e) => setSystem1BaseUrl(e.target.value)}
                placeholder={
                  system1ApiMode === 'typesafe'
                    ? 'https://api.typesafe.ai (default)'
                    : 'https://openrouter.ai/api/v1'
                }
                className={`${inputClass} font-mono`}
              />
            </Field>

            <Field label="System-1 Model">
              <input
                type="text"
                value={system1Model}
                onChange={(e) => setSystem1Model(e.target.value)}
                placeholder="e.g. jev-latest or an OpenRouter model id"
                className={`${inputClass} font-mono`}
              />
            </Field>

            <Field label="System-1 API Key" hint="Leave blank to keep the stored key." className="sm:col-span-2">
              <div className="relative">
                <input
                  type={showSystem1Key ? 'text' : 'password'}
                  value={system1ApiKey}
                  onChange={(e) => setSystem1ApiKey(e.target.value)}
                  placeholder="Stored key is preserved when left blank"
                  className={`${inputClass} pr-10 font-mono`}
                />
                <button
                  type="button"
                  onClick={() => setShowSystem1Key((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 transition hover:text-zinc-200"
                >
                  {showSystem1Key ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                </button>
              </div>
            </Field>
          </div>
        )}
      </div>

      {/* Workspace telemetry */}
      <div className="space-y-1.5 rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-3 text-[11px]">
        <div className="flex items-center gap-1.5 font-semibold text-zinc-300">
          <Server className="h-3.5 w-3.5 text-violet-400" />
          Workspace &amp; Grounding Telemetry
        </div>
        <div className="grid grid-cols-1 gap-1.5 font-mono text-[10px] text-zinc-400 sm:grid-cols-2">
          <div>
            Workspace: <span className="text-zinc-200">{workspaceDir || '—'}</span>
          </div>
          <div>
            Database: <span className="text-zinc-200">{databaseUrl || '—'}</span>
          </div>
          <div>
            System-1 Verifier: <span className="text-emerald-400">{system1Provider}</span>
          </div>
          <div>
            Embedding Model: <span className="text-zinc-200">{embeddingModel || '—'}</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <Button type="button" disabled={loading} onClick={() => void loadSettings()}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Reload
        </Button>
        <Button type="submit" variant="primary" disabled={saving}>
          {saving ? (
            <div className="h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {saving ? 'Saving…' : 'Save & Apply'}
        </Button>
      </div>

      {!compact && (
        <div className="flex flex-wrap gap-2 pt-1">
          <Badge tone="emerald">Zero Hallucination</Badge>
          <Badge tone="violet">Bring Your Own API</Badge>
        </div>
      )}
    </form>
  );
};
