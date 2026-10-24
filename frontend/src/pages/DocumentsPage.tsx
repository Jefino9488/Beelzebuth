/**
 * Document repository & ingestion.
 * Replaces the Jinja `files.html` template: searchable document list with version
 * counts, tenant scope, and an upload panel that ingests straight into the vector store.
 */

import React, { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Upload, Search, Workflow, ListFilter, X } from 'lucide-react';
import { api } from '../lib/api';
import { useApiData } from '../lib/useApi';
import {
  PageHeader,
  Panel,
  Table,
  Th,
  Td,
  Badge,
  Button,
  EmptyState,
  Alert,
  Loading,
  inputClass,
  Field,
} from '../components/ui';

interface FileVersion {
  version_number: number;
  file_size: number;
  mime_type: string;
  file_hash: string;
  created_at: string;
}

interface FileRecord {
  id: string;
  name: string;
  organisation_id: string;
  folder_id: string | null;
  created_by_user_id: string | null;
  versions: FileVersion[];
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const DocumentsPage: React.FC = () => {
  const { data, loading, error, reload } = useApiData<FileRecord[]>('/api/files');
  const [search, setSearch] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const files = useMemo(() => data ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return files;
    return files.filter((f) => f.name.toLowerCase().includes(needle));
  }, [files, search]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    setUploadNotice(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.upload<FileRecord>('/api/files/upload', form);
      const versions = res.versions?.length ?? 0;
      setUploadNotice(`Successfully ingested '${res.name}' (v${versions}) and indexed it into the vector store.`);
      setShowUpload(false);
      reload();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <div>
      <PageHeader
        title="Document Ingestion & File Explorer"
        description="Every document is versioned, hashed and chunked with section provenance before it is indexed into the tenant-scoped vector store."
        action={
          <Button variant="primary" onClick={() => setShowUpload((v) => !v)}>
            <Upload className="h-3.5 w-3.5" />
            Ingest Document
          </Button>
        }
      />

      {uploadNotice && (
        <div className="mb-3">
          <Alert tone="emerald">{uploadNotice}</Alert>
        </div>
      )}

      {showUpload && (
        <Panel title="Ingest a new document" className="mb-4">
          {uploadError && (
            <div className="mb-3">
              <Alert tone="rose">{uploadError}</Alert>
            </div>
          )}
          <Field
            label="Source file"
            hint="PDF, DOCX, PPTX, XLSX, CSV, TXT, Markdown and HTML are supported."
          >
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.html"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleUpload(file);
              }}
              className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs text-zinc-300 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-800 file:px-2.5 file:py-1 file:text-[11px] file:text-zinc-200"
            />
          </Field>
          {uploading && (
            <p className="mt-2 text-[11px] text-zinc-400">
              Extracting, chunking and indexing… this can take a moment for large documents.
            </p>
          )}
        </Panel>
      )}

      <Panel
        title={`Indexed Documents (${filtered.length})`}
        action={
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search documents…"
              className={`${inputClass} pl-8`}
            />
          </div>
        }
        bodyClassName="p-0"
      >
        {loading ? (
          <div className="p-4">
            <Loading label="Loading documents…" />
          </div>
        ) : error ? (
          <div className="p-4">
            <Alert tone="rose">{error}</Alert>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<FileText className="h-7 w-7" />}
              title={search ? 'No documents match your search' : 'No documents ingested yet'}
              description={
                search
                  ? 'Try a different search term.'
                  : 'Ingest a document to populate the evidence pipeline.'
              }
              action={
                search ? (
                  <Button onClick={() => setSearch('')}>
                    <X className="h-3.5 w-3.5" />
                    Clear search
                  </Button>
                ) : (
                  <Button variant="primary" onClick={() => setShowUpload(true)}>
                    <Upload className="h-3.5 w-3.5" />
                    Ingest Document
                  </Button>
                )
              }
            />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Document</Th>
                <Th>Type</Th>
                <Th>Versions</Th>
                <Th>Size</Th>
                <Th>Integrity</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((file) => {
                const latest = file.versions?.length
                  ? file.versions.reduce((acc, v) => (v.version_number > acc.version_number ? v : acc))
                  : null;
                return (
                  <tr key={file.id} className="hover:bg-zinc-900/40">
                    <Td>
                      <Link
                        to={`/documents/${file.id}/spans`}
                        className="flex items-center gap-1.5 text-zinc-200 transition hover:text-violet-300"
                      >
                        <FileText className="h-3 w-3 text-zinc-500" />
                        <span className="truncate">{file.name}</span>
                      </Link>
                    </Td>
                    <Td>
                      <Badge tone="neutral" mono>
                        {file.name.split('.').pop()?.toUpperCase() ?? 'FILE'}
                      </Badge>
                    </Td>
                    <Td className="font-mono text-zinc-500">v{file.versions?.length ?? 0}</Td>
                    <Td className="font-mono text-zinc-500">
                      {latest ? formatSize(latest.file_size) : '—'}
                    </Td>
                    <Td>
                      <span className="font-mono text-[10px] text-zinc-600">
                        {latest ? `${latest.file_hash.slice(0, 12)}…` : '—'}
                      </span>
                    </Td>
                    <Td>
                      <div className="flex items-center gap-1.5">
                        <Link
                          to={`/documents/${file.id}/spans`}
                          className="rounded-md border border-zinc-800 px-2 py-1 text-[10px] text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
                        >
                          Spans
                        </Link>
                        <Link
                          to={`/process-graph?file_id=${file.id}`}
                          className="flex items-center gap-1 rounded-md border border-zinc-800 px-2 py-1 text-[10px] text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
                        >
                          <Workflow className="h-3 w-3" />
                          Graph
                        </Link>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
};

export default DocumentsPage;
