import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiPlus, FiRefreshCw, FiEdit2, FiGift, FiUsers, FiX, FiCheckCircle, FiAlertCircle } from 'react-icons/fi';

const EMPTY = { name: '', plan_id: '', start_at: '', end_at: '', duration_days: 7, apply_to_new_drivers: true, apply_to_existing: false, is_active: true, max_redemptions: '', notes: '' };
const localDate = (value) => value ? new Date(new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '';
const payloadDate = (value) => value ? new Date(value).toISOString() : '';

function PolicyModal({ policy, plans, onClose, onSaved }) {
  const [form, setForm] = useState(() => policy ? {
    name: policy.name || '', plan_id: String(policy.plan_id || ''), start_at: localDate(policy.start_at), end_at: localDate(policy.end_at),
    duration_days: policy.duration_days || 7, apply_to_new_drivers: !!policy.apply_to_new_drivers,
    apply_to_existing: !!policy.apply_to_existing, is_active: !!policy.is_active,
    max_redemptions: policy.max_redemptions ?? '', notes: policy.notes || '',
  } : { ...EMPTY, plan_id: String(plans[0]?.id || '') });
  const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const save = async (event) => {
    event.preventDefault(); setError('');
    if (!form.name.trim()) return setError('Enter an offer name.');
    if (!form.plan_id) return setError('Choose a subscription package.');
    if (!form.start_at || !form.end_at || new Date(form.end_at) <= new Date(form.start_at)) return setError('Choose a valid date range.');
    if (!Number.isInteger(Number(form.duration_days)) || Number(form.duration_days) < 1) return setError('Grace duration must be at least one day.');
    if (form.max_redemptions !== '' && (!Number.isInteger(Number(form.max_redemptions)) || Number(form.max_redemptions) < 1)) return setError('Redemption limit must be a positive whole number or left blank.');
    const data = { ...form, plan_id: Number(form.plan_id), duration_days: Number(form.duration_days), max_redemptions: form.max_redemptions === '' ? null : Number(form.max_redemptions), start_at: payloadDate(form.start_at), end_at: payloadDate(form.end_at) };
    setSaving(true);
    try {
      const response = policy ? await adminAPI.gracePolicyUpdate(policy.id, data) : await adminAPI.gracePolicyCreate(data);
      onSaved(response.data?.data || {});
    } catch (e) { setError(e?.response?.data?.message || 'Could not save this offer. Check your connection and try again.'); }
    finally { setSaving(false); }
  };
  return <div className="modal-overlay grace-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="modal-box grace-modal" role="dialog" aria-modal="true" aria-labelledby="grace-modal-title">
      <header className="grace-modal-head"><div className="grace-modal-icon"><FiGift /></div><div><h2 id="grace-modal-title">{policy ? 'Edit grace offer' : 'Create grace offer'}</h2><p>Control eligibility and the package drivers receive automatically.</p></div><button className="drawer-close" aria-label="Close" onClick={onClose}><FiX /></button></header>
      <form onSubmit={save}>
        <div className="grace-modal-body">
          <div className="grace-form-section"><h3>Offer setup</h3><div className="grace-form-grid">
            <label className="form-group grace-span-2"><span>Offer name</span><input className="d-input" value={form.name} maxLength="120" onChange={(e) => set('name', e.target.value)} placeholder="Example: New driver launch offer" /></label>
            <label className="form-group grace-span-2"><span>Package to assign</span><select className="d-input" value={form.plan_id} onChange={(e) => set('plan_id', e.target.value)}><option value="">Select a package</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.period} · ₦{Number(p.amount || 0).toLocaleString()}</option>)}</select></label>
            <label className="form-group"><span>Offer starts</span><input className="d-input" type="datetime-local" value={form.start_at} onChange={(e) => set('start_at', e.target.value)} /></label>
            <label className="form-group"><span>Signup deadline</span><input className="d-input" type="datetime-local" value={form.end_at} onChange={(e) => set('end_at', e.target.value)} /></label>
            <label className="form-group"><span>Free package duration (days)</span><input className="d-input" type="number" min="1" step="1" value={form.duration_days} onChange={(e) => set('duration_days', e.target.value)} /></label>
            <label className="form-group"><span>Maximum redemptions</span><input className="d-input" type="number" min="1" step="1" value={form.max_redemptions} onChange={(e) => set('max_redemptions', e.target.value)} placeholder="Unlimited" /></label>
          </div></div>
          <div className="grace-form-section"><h3>Who can receive this offer?</h3><div className="grace-audience-grid">
            <label className={`grace-choice ${form.apply_to_new_drivers ? 'selected' : ''}`}><input type="checkbox" checked={form.apply_to_new_drivers} onChange={(e) => set('apply_to_new_drivers', e.target.checked)} /><span><b>New driver signups</b><small>Drivers registering during the offer window</small></span></label>
            <label className={`grace-choice ${form.apply_to_existing ? 'selected' : ''}`}><input type="checkbox" checked={form.apply_to_existing} onChange={(e) => set('apply_to_existing', e.target.checked)} /><span><b>Existing pending drivers</b><small>Eligible pending drivers receive it when this offer is saved</small></span></label>
          </div></div>
          <div className="grace-form-section"><h3>Availability</h3><label className={`grace-choice ${form.is_active ? 'selected' : ''}`}><input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} /><span><b>Offer enabled</b><small>When disabled, new drivers cannot redeem this offer.</small></span></label><label className="form-group" style={{ marginTop: 14 }}><span>Internal notes (optional)</span><textarea className="d-input" rows="3" maxLength="2000" value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Visible to admins only" /></label></div>
          {policy && <p className="grace-edit-note">Package and duration changes also update active grace subscriptions linked to this offer. Date and audience changes affect future eligibility immediately.</p>}
          {error && <div className="grace-form-error"><FiAlertCircle />{error}</div>}
        </div>
        <footer className="grace-modal-footer"><button type="button" className="btn btn-sm" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="btn btn-sm btn-accent" disabled={saving}>{saving ? 'Saving changes…' : policy ? 'Save changes' : 'Create offer'}</button></footer>
      </form>
    </section>
  </div>;
}

export default function GraceOffersPage() {
  const [policies, setPolicies] = useState([]); const [plans, setPlans] = useState([]); const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try { const { data } = await adminAPI.gracePolicies(); setPolicies(data.data || []); } catch (e) { setError(e?.response?.data?.message || 'Could not load grace offers.'); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); fetch('/api/subscription-plans').then((r) => r.json()).then((d) => setPlans(d.data || [])).catch(() => setError('Could not load subscription packages.')); }, [load]);
  const stats = useMemo(() => ({ total: policies.length, enabled: policies.filter((p) => p.is_active).length, redemptions: policies.reduce((n, p) => n + Number(p.redemption_count || 0), 0) }), [policies]);
  const saveDone = async (result) => { setEditing(null); setNotice(`Offer saved.${result.existing_drivers_applied ? ` Applied to ${result.existing_drivers_applied} pending drivers.` : ''}`); await load(); window.setTimeout(() => setNotice(''), 5000); };
  const statusOf = (p) => { const now = Date.now(); if (!p.is_active) return 'Disabled'; if (new Date(p.start_at).getTime() > now) return 'Scheduled'; if (new Date(p.end_at).getTime() < now) return 'Ended'; if (p.max_redemptions && p.redemption_count >= p.max_redemptions) return 'Fully redeemed'; return 'Live'; };
  return <div className="page-subscriptions grace-offers-page">
    {editing && <PolicyModal policy={editing === 'new' ? null : editing} plans={plans} onClose={() => setEditing(null)} onSaved={saveDone} />}
    <div className="page-toolbar grace-page-toolbar"><div><div className="grace-eyebrow">DRIVER PROGRAMS</div><h1>Grace offers</h1><p className="muted">Manage automatic package offers for new and pending drivers.</p></div><div className="grace-toolbar-actions"><button className="btn btn-sm" onClick={load} disabled={loading}><FiRefreshCw /> Refresh</button><button className="btn btn-sm btn-accent" onClick={() => setEditing('new')}><FiPlus /> Create offer</button></div></div>
    {notice && <div className="grace-notice"><FiCheckCircle />{notice}</div>}{error && <div className="grace-form-error"><FiAlertCircle />{error}<button className="btn btn-xs" onClick={load}>Retry</button></div>}
    <div className="grace-stats"><div className="content-card"><span>Total offers</span><b>{stats.total}</b></div><div className="content-card"><span>Enabled offers</span><b>{stats.enabled}</b></div><div className="content-card"><span>Total redemptions</span><b>{stats.redemptions}</b></div></div>
    <div className="content-card grace-table-card"><div className="grace-table-heading"><div><h2>Configured offers</h2><p className="muted">Changes to an offer take effect as soon as they are saved.</p></div></div>
      {loading ? <div className="page-loader">Loading offers…</div> : <div className="table-wrap"><table><thead><tr><th>Offer</th><th>Package</th><th>Signup window</th><th>Free duration</th><th>Audience</th><th>Redemptions</th><th>Status</th><th></th></tr></thead><tbody>{policies.map((p) => <tr key={p.id}><td><div className="grace-offer-name"><b>{p.name}</b>{p.notes && <small>{p.notes}</small>}</div></td><td>{p.plan?.name || '—'}</td><td>{new Date(p.start_at).toLocaleString()}<small className="grace-date-end">through {new Date(p.end_at).toLocaleString()}</small></td><td>{p.duration_days} days</td><td>{[p.apply_to_new_drivers && 'New drivers', p.apply_to_existing && 'Pending drivers'].filter(Boolean).join(', ') || 'No audience selected'}</td><td>{p.redemption_count || 0}{p.max_redemptions ? ` / ${p.max_redemptions}` : ' / ∞'}</td><td><span className={`grace-status grace-status-${statusOf(p).toLowerCase().replaceAll(' ', '-')}`}>{statusOf(p)}</span></td><td><button className="btn btn-xs" onClick={() => setEditing(p)}><FiEdit2 /> Edit</button></td></tr>)}</tbody></table>{!policies.length && <div className="empty-state">No grace offers yet. Create an offer to configure the package and eligible drivers.</div>}</div>}
    </div>
  </div>;
}
