/**
 * Tenant & identity administration.
 * Replaces the Jinja `admin.html` template: onboard organisations, approve or suspend
 * them, assign client super admins, and provision employees.
 */

import React, { useMemo, useState } from 'react';
import { Building2, Plus, CheckCircle2, Ban, UserPlus, Users } from 'lucide-react';
import { api } from '../lib/api';
import { useApiData } from '../lib/useApi';
import { useProfile } from '../lib/useProfile';
import {
  PageHeader,
  Panel,
  Table,
  Th,
  Td,
  Badge,
  Button,
  Alert,
  Loading,
  Field,
  inputClass,
  selectClass,
  EmptyState,
} from '../components/ui';

interface OrganisationEntry {
  id: string;
  name: string;
  status: string;
  user_count: number;
  file_count: number;
  created_at: string;
}

interface ConsoleUserEntry {
  id: string;
  email: string;
  role: string;
  organisation_id: string | null;
  is_active: boolean;
  created_at: string;
}

const STATUS_TONE: Record<string, 'emerald' | 'amber' | 'rose'> = {
  APPROVED: 'emerald',
  PENDING: 'amber',
  SUSPENDED: 'rose',
};

export const TenantAdminPage: React.FC = () => {
  const { profile } = useProfile();
  const isSuperAdmin = profile?.role === 'SUPER_ADMIN';

  const { data: orgs, loading, error, reload } = useApiData<OrganisationEntry[]>(
    '/api/v1/console/organisations'
  );
  const [selectedOrg, setSelectedOrg] = useState<string>('');
  const { data: users, reload: reloadUsers } = useApiData<ConsoleUserEntry[]>(
    selectedOrg ? `/api/v1/console/organisations/${selectedOrg}/users` : null
  );

  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [orgName, setOrgName] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [employeeEmail, setEmployeeEmail] = useState('');
  const [employeePassword, setEmployeePassword] = useState('');
  const [employeeOrg, setEmployeeOrg] = useState('');

  const organisationList = useMemo(() => orgs ?? [], [orgs]);
  const activeOrg = selectedOrg || employeeOrg || organisationList[0]?.id || '';

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setNotice(null);
    setFailure(null);
    try {
      setNotice(await fn());
      reload();
      reloadUsers();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  };

  const createOrganisation = () =>
    run(async () => {
      await api.post('/api/admin/organisations', { name: orgName.trim() });
      setOrgName('');
      return `Successfully onboarded organisation '${orgName.trim()}'.`;
    });

  const setOrgStatus = (orgId: string, action: 'approve' | 'suspend') =>
    run(async () => {
      await api.post(`/api/admin/organisations/${orgId}/${action}`);
      return `Organisation ${action === 'approve' ? 'approved' : 'suspended'}.`;
    });

  const createAdmin = () =>
    run(async () => {
      await api.post(`/api/admin/organisations/${activeOrg}/admins`, {
        email: adminEmail.trim(),
        password: adminPassword,
      });
      setAdminEmail('');
      setAdminPassword('');
      return `Assigned Client Super Admin '${adminEmail.trim()}'.`;
    });

  const createEmployee = () =>
    run(async () => {
      const organisation = employeeOrg || activeOrg;
      await api.post('/api/tenant/employees', {
        email: employeeEmail.trim(),
        password: employeePassword,
        ...(organisation ? { organisation_id: organisation } : {}),
      });
      setEmployeeEmail('');
      setEmployeePassword('');
      return `Provisioned employee '${employeeEmail.trim()}'.`;
    });

  if (loading) return <Loading label="Loading tenants…" />;
  if (error) return <Alert tone="rose">{error}</Alert>;

  return (
    <div>
      <PageHeader
        title="Tenants & Identity Administration"
        description="Onboard organisations, control their lifecycle, and provision client administrators and employees."
      />

      {notice && (
        <div className="mb-3">
          <Alert tone="emerald">{notice}</Alert>
        </div>
      )}
      {failure && (
        <div className="mb-3">
          <Alert tone="rose">{failure}</Alert>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Panel title={`Organisations (${organisationList.length})`} bodyClassName="p-0">
            {organisationList.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={<Building2 className="h-7 w-7" />}
                  title="No tenants onboarded"
                  description="Create an organisation to begin provisioning users."
                />
              </div>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Organisation</Th>
                    <Th>Tenant ID</Th>
                    <Th>Users</Th>
                    <Th>Documents</Th>
                    <Th>Status</Th>
                    <Th>Created</Th>
                    {isSuperAdmin && <Th>Actions</Th>}
                  </tr>
                </thead>
                <tbody>
                  {organisationList.map((org) => (
                    <tr
                      key={org.id}
                      onClick={() => setSelectedOrg(org.id)}
                      className={`cursor-pointer hover:bg-zinc-900/40 ${selectedOrg === org.id ? 'bg-violet-950/30' : ''}`}
                    >
                      <Td className="font-medium text-zinc-200">{org.name}</Td>
                      <Td className="font-mono text-[10px] text-zinc-600">{org.id}</Td>
                      <Td className="font-mono text-zinc-500">{org.user_count}</Td>
                      <Td className="font-mono text-zinc-500">{org.file_count}</Td>
                      <Td>
                        <Badge tone={STATUS_TONE[org.status] ?? 'neutral'}>{org.status}</Badge>
                      </Td>
                      <Td className="whitespace-nowrap text-zinc-500">
                        {new Date(org.created_at).toLocaleDateString()}
                      </Td>
                      {isSuperAdmin && (
                        <Td>
                          <div className="flex gap-1.5">
                            {org.status !== 'APPROVED' && (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void setOrgStatus(org.id, 'approve');
                                }}
                                className="rounded-md border border-emerald-800/60 bg-emerald-950/50 px-2 py-1 text-[10px] text-emerald-300 transition hover:bg-emerald-900/50"
                              >
                                <CheckCircle2 className="mr-1 inline h-3 w-3" />
                                Approve
                              </button>
                            )}
                            {org.status !== 'SUSPENDED' && (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void setOrgStatus(org.id, 'suspend');
                                }}
                                className="rounded-md border border-rose-800/60 bg-rose-950/50 px-2 py-1 text-[10px] text-rose-300 transition hover:bg-rose-900/50"
                              >
                                <Ban className="mr-1 inline h-3 w-3" />
                                Suspend
                              </button>
                            )}
                          </div>
                        </Td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Panel>

          <Panel title={`Users${activeOrg ? ` — ${organisationList.find((o) => o.id === activeOrg)?.name ?? ''}` : ''}`} bodyClassName="p-0">
            {!activeOrg ? (
              <div className="p-4 text-xs text-zinc-600">Select an organisation to list its users.</div>
            ) : !users || users.length === 0 ? (
              <div className="p-4 text-xs text-zinc-600">No users provisioned in this organisation yet.</div>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Email</Th>
                    <Th>Role</Th>
                    <Th>Status</Th>
                    <Th>Created</Th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((entry) => (
                    <tr key={entry.id} className="hover:bg-zinc-900/40">
                      <Td className="text-zinc-200">{entry.email}</Td>
                      <Td>
                        <Badge tone={entry.role === 'CLIENT_ADMIN' ? 'sky' : 'neutral'}>{entry.role}</Badge>
                      </Td>
                      <Td>
                        <Badge tone={entry.is_active ? 'emerald' : 'rose'}>
                          {entry.is_active ? 'Active' : 'Disabled'}
                        </Badge>
                      </Td>
                      <Td className="whitespace-nowrap text-zinc-500">
                        {new Date(entry.created_at).toLocaleDateString()}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Panel>
        </div>

        <div className="space-y-4">
          {isSuperAdmin && (
            <Panel title="Onboard Organisation">
              <div className="space-y-3">
                <Field label="Organisation name">
                  <input
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="e.g. Acme Financial"
                    className={inputClass}
                  />
                </Field>
                <Button variant="primary" className="w-full" disabled={busy || !orgName.trim()} onClick={() => void createOrganisation()}>
                  <Plus className="h-3.5 w-3.5" />
                  Onboard Organisation
                </Button>
              </div>
            </Panel>
          )}

          {isSuperAdmin && (
            <Panel title="Assign Client Super Admin">
              <div className="space-y-3">
                <Field label="Organisation">
                  <select value={activeOrg} onChange={(e) => setSelectedOrg(e.target.value)} className={selectClass}>
                    <option value="">Select…</option>
                    {organisationList.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Admin email">
                  <input
                    type="email"
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    placeholder="admin@acme.com"
                    className={inputClass}
                  />
                </Field>
                <Field label="Temporary password">
                  <input
                    type="password"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    className={inputClass}
                  />
                </Field>
                <Button
                  variant="primary"
                  className="w-full"
                  disabled={busy || !activeOrg || !adminEmail.trim() || !adminPassword}
                  onClick={() => void createAdmin()}
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  Assign Admin
                </Button>
              </div>
            </Panel>
          )}

          <Panel title="Provision Employee">
            <div className="space-y-3">
              <Field label="Organisation">
                <select value={employeeOrg} onChange={(e) => setEmployeeOrg(e.target.value)} className={selectClass}>
                  <option value="">Select…</option>
                  {organisationList.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Employee email">
                <input
                  type="email"
                  value={employeeEmail}
                  onChange={(e) => setEmployeeEmail(e.target.value)}
                  placeholder="employee@acme.com"
                  className={inputClass}
                />
              </Field>
              <Field label="Temporary password">
                <input
                  type="password"
                  value={employeePassword}
                  onChange={(e) => setEmployeePassword(e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Button
                variant="primary"
                className="w-full"
                disabled={busy || !employeeEmail.trim() || !employeePassword}
                onClick={() => void createEmployee()}
              >
                <Users className="h-3.5 w-3.5" />
                Provision Employee
              </Button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
};

export default TenantAdminPage;
