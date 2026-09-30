import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiCheckCircle, FiXCircle, FiPlus, FiX, FiAlertTriangle } from 'react-icons/fi';

const STATUS_COLORS = { active: '#2e7d32', pending: '#f59e0b', expired: '#888', cancelled: '#f44336' };

function Confirm({ message, confirmLabel, danger, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 16 }}>
          <FiAlertTriangle size={22} color={danger ? '#f44336' : '#f59e0b'} style={{ flexShrink: 0, marginTop: 2 }} />
          <p>{message}</p>
        </div>
        <div className="modal-actions">
          <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
          <button className={`btn btn-sm ${danger ? 'btn-danger' : 'btn-accent'}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

function GrantDrawer({ plans, onClose, onSaved }) {
  const [driverId, setDriverId] = useState('');
  const [planId, setPlanId] = useState(plans[0]?.id || '');
  const [days, setDays] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const save = async () => {
    if (!driverId || !planId) { setErr('Driver ID and plan are required'); return; }
    setSaving(true); setErr('');
    try {
      await adminAPI.subscriptionGrant({ driver_id: driverId, plan_id: planId, duration_days: days || undefined });
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to grant');
    } finally { setSaving(false); }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 400 }}>
        <div className="drawer-head">
          <h2>Grant Subscription</h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="form-grid" style={{ gridTemplateColumns: '1fr', gap: 12 }}>
            <div className="form-group">
              <label>Driver User ID *</label>
              <input className="d-input" type="number" value={driverId} onChange={(e) => setDriverId(e.target.value)} placeholder="e.g. 1042" />
            </div>
            <div className="form-group">
              <label>Plan *</label>
              <select className="d-input" value={planId} onChange={(e) => setPlanId(e.target.value)}>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name} — ₦{Number(p.amount).toLocaleString()} ({p.period})</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Duration override (days, optional)</label>
              <input className="d-input" type="number" value={days} onChange={(e) => setDays(e.target.value)} placeholder="defaults to plan duration" />
            </div>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 10 }}>
            Creates and immediately activates a subscription for this driver (comped / offline-paid).
          </p>
          {err && <p style={{ color: 'var(--error)', fontSize: 13, marginTop: 10 }}>{err}</p>}
        </div>
        <div className="drawer-footer">
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save} style={{ flex: 1 }}>
            {saving ? 'Granting…' : 'Grant & Activate'}
          </button>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function GraceOfferDrawer({ plans, onClose, onSaved }) {
  const [form, setForm] = useState({ name: 'New driver grace offer', plan_id: plans[0]?.id || '', start_at: '', end_at: '', duration_days: 7, apply_to_new_drivers: true, apply_to_existing: false });
  const [saving, setSaving] = useState(false); const [err, setErr] = useState('');
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const save = async () => {
    if (!form.plan_id || !form.start_at || !form.end_at) { setErr('Package, start date, and end date are required'); return; }
    setSaving(true); setErr('');
    try { await adminAPI.gracePolicyCreate(form); onSaved(); } catch (e) { setErr(e?.response?.data?.message || 'Unable to save offer'); } finally { setSaving(false); }
  };
  return <div className="drawer-overlay" onClick={onClose}><div className="drawer-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
    <div className="drawer-head"><h2>New Driver Grace Offer</h2><button className="drawer-close" onClick={onClose}><FiX /></button></div>
    <div className="drawer-body"><p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Drivers who register during this window receive the selected package automatically without payment.</p>
      <div className="form-grid" style={{ gridTemplateColumns: '1fr', gap: 10 }}>
        <input className="d-input" placeholder="Offer name" value={form.name} onChange={(e) => set('name', e.target.value)} />
        <select className="d-input" value={form.plan_id} onChange={(e) => set('plan_id', e.target.value)}>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.period})</option>)}</select>
        <label>Starts <input className="d-input" type="datetime-local" value={form.start_at} onChange={(e) => set('start_at', e.target.value)} /></label>
        <label>Ends <input className="d-input" type="datetime-local" value={form.end_at} onChange={(e) => set('end_at', e.target.value)} /></label>
        <label>Grace duration (days) <input className="d-input" type="number" min="1" value={form.duration_days} onChange={(e) => set('duration_days', e.target.value)} /></label>
        <label><input type="checkbox" checked={form.apply_to_new_drivers} onChange={(e) => set('apply_to_new_drivers', e.target.checked)} /> New driver signups</label>
        <label><input type="checkbox" checked={form.apply_to_existing} onChange={(e) => set('apply_to_existing', e.target.checked)} /> Existing pending drivers</label>
      </div>{err && <p style={{ color: 'var(--error)', fontSize: 13 }}>{err}</p>}
    </div><div className="drawer-footer"><button className="btn btn-sm btn-accent" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save Grace Offer'}</button><button className="btn btn-sm" onClick={onClose}>Cancel</button></div>
  </div></div>;
}

export default function SubscriptionsPage() {
  const [rows, setRows] = useState([]);
  const [plans, setPlans] = useState([]);
  const [stats, setStats] = useState({ active_count: 0, active_revenue: 0 });
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState({});
  const [confirm, setConfirm] = useState(null);
  const [granting, setGranting] = useState(false);
  const [gracePolicies, setGracePolicies] = useState([]);
  const [creatingGrace, setCreatingGrace] = useState(false);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.subscriptions(filter ? { status: filter } : {})
      .then(({ data }) => {
        if (data.code === 1) {
          setRows(data.data?.subscriptions || []);
          setStats({ active_count: data.data?.active_count || 0, active_revenue: data.data?.active_revenue || 0 });
        } else setError(data.message);
      })
      .catch((err) => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);
  useEffect(() => {
    // load plans for the grant form
    fetch('/api/subscription-plans').then((r) => r.json()).then((d) => setPlans(d.data || [])).catch(() => {});
    adminAPI.gracePolicies().then(({ data }) => setGracePolicies(data.data || [])).catch(() => {});
  }, []);

  const act = async (id, fn) => {
    setBusy((b) => ({ ...b, [id]: true }));
    try { await fn(); load(); } catch {} finally { setBusy((b) => ({ ...b, [id]: false })); setConfirm(null); }
  };

  const money = (v) => `₦${Number(v || 0).toLocaleString()}`;

  return (
    <div className="page-subscriptions">
      {granting && <GrantDrawer plans={plans} onClose={() => setGranting(false)} onSaved={() => { setGranting(false); load(); }} />}
      {creatingGrace && <GraceOfferDrawer plans={plans} onClose={() => setCreatingGrace(false)} onSaved={() => { setCreatingGrace(false); adminAPI.gracePolicies().then(({ data }) => setGracePolicies(data.data || [])); }} />}
      {confirm && (
        <Confirm
          message={confirm.message}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          onCancel={() => setConfirm(null)}
          onConfirm={confirm.onConfirm}
        />
      )}

      <div className="page-toolbar">
        <span className="toolbar-info">Active: <b>{stats.active_count}</b></span>
        <span className="toolbar-info">Active revenue: <b>{money(stats.active_revenue)}</b></span>
        <select className="d-input" style={{ maxWidth: 150 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="pending">Pending</option>
          <option value="expired">Expired</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <button className="btn btn-sm btn-accent" onClick={() => setGranting(true)}><FiPlus /> Grant Subscription</button>
      </div>
      <section className="content-card" style={{ marginBottom: 18 }}>
        <div className="section-header"><div><h2>Driver Grace Offers</h2><p className="muted">Automatic package access for eligible driver registrations.</p></div><button className="btn btn-sm btn-accent" onClick={() => setCreatingGrace(true)}><FiPlus /> Create offer</button></div>
        {gracePolicies.length ? <div className="table-wrap"><table><thead><tr><th>Offer</th><th>Package</th><th>Window</th><th>Duration</th><th>Audience</th><th>Status</th></tr></thead><tbody>{gracePolicies.map((p) => <tr key={p.id}><td><b>{p.name}</b></td><td>{p.plan?.name || '—'}</td><td>{new Date(p.start_at).toLocaleDateString()} – {new Date(p.end_at).toLocaleDateString()}</td><td>{p.duration_days} days</td><td>{[p.apply_to_new_drivers && 'New drivers', p.apply_to_existing && 'Existing pending'].filter(Boolean).join(', ') || 'None'}</td><td><span className="status-pill">{p.is_active ? 'Active' : 'Inactive'}</span></td></tr>)}</tbody></table></div> : <p className="empty-state">No grace offers configured yet.</p>}
      </section>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Driver</th><th>Plan</th><th>Amount</th><th>Status</th><th>Start</th><th>End</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const b = busy[s.id];
                const isActive = s.status === 'active';
                return (
                  <tr key={s.id}>
                    <td style={{ fontWeight: 700 }}>#{s.id}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{s.driver_name || `#${s.driver_id}`}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{s.driver_email || s.driver_phone || ''}</div>
                    </td>
                    <td>{s.plan?.name || '—'}</td>
                    <td>{money(s.amount)}</td>
                    <td><span style={{ color: STATUS_COLORS[s.status] || '#888', fontWeight: 600 }}>{s.status}</span></td>
                    <td>{s.start_at ? new Date(s.start_at).toLocaleDateString() : '—'}</td>
                    <td>{s.end_at ? new Date(s.end_at).toLocaleDateString() : '—'}</td>
                    <td className="actions">
                      {!isActive && (
                        <button className="btn btn-xs" title="Mark Paid & Active" disabled={b}
                          style={{ borderColor: '#2e7d32', color: '#2e7d32' }}
                          onClick={() => setConfirm({
                            message: `Mark subscription #${s.id} (${s.driver_name || '#' + s.driver_id}) as PAID & ACTIVE?`,
                            confirmLabel: 'Activate',
                            onConfirm: () => act(s.id, () => adminAPI.subscriptionActivate(s.id)),
                          })}>
                          <FiCheckCircle size={13} /> Activate
                        </button>
                      )}
                      {isActive && (
                        <button className="btn btn-xs btn-danger" title="Cancel subscription" disabled={b}
                          onClick={() => setConfirm({
                            message: `Cancel subscription #${s.id} (${s.driver_name || '#' + s.driver_id})? The driver will be taken offline.`,
                            confirmLabel: 'Cancel subscription', danger: true,
                            onConfirm: () => act(s.id, () => adminAPI.subscriptionCancel(s.id)),
                          })}>
                          <FiXCircle size={13} /> Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan="8" className="empty-state">No subscriptions found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
