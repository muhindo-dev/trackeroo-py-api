import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { adminAPI } from '../services/api';
import {
  FiSearch, FiChevronLeft, FiChevronRight, FiX, FiEye, FiXCircle,
  FiAlertTriangle, FiSave, FiPlay, FiRefreshCw, FiCheck,
} from 'react-icons/fi';

const RideSimulatorModal = React.lazy(() => import('./RideSimulatorModal'));

const N_STATUSES = ['', 'Pending', 'Active', 'Accepted', 'Started', 'Completed', 'Cancelled'];
const PAY_FILTERS = ['', 'paid', 'unpaid'];
const PER_PAGE = 20;

/* Money on this model is stored in CENTS; `fare` is the display-ready figure
 * the API already converts. Prefer it, and only fall back to dividing. */
const money = (n) => (n == null || n === '' ? '—' : `₦${Number(n).toLocaleString()}`);
const fromCents = (c) => (c == null || c === '' ? '' : String(Number(c) / 100));

function Confirm({ message, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 16 }}>
          <FiAlertTriangle size={22} color="#f44336" style={{ flexShrink: 0, marginTop: 2 }} />
          <p>{message}</p>
        </div>
        <div className="modal-actions">
          <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
          <button className="btn btn-sm btn-danger" onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}

/* ── editable field descriptors, so the form stays declarative ─────────── */
const EDIT_GROUPS = [
  {
    title: 'Lifecycle',
    fields: [
      { key: 'status', label: 'Status', type: 'select', options: ['Pending', 'Active', 'Accepted', 'Started', 'Completed', 'Cancelled'] },
      { key: 'is_active', label: 'Is active', type: 'select', options: ['Yes', 'No'] },
      { key: 'customer_accepted', label: 'Customer accepted', type: 'select', options: ['Pending', 'Accepted', 'Rejected'] },
      { key: 'customer_driver', label: 'Driver accepted', type: 'select', options: ['Pending', 'Accepted', 'Rejected'] },
      { key: 'ride_source', label: 'Ride source', type: 'text' },
      { key: 'scheduled_at', label: 'Scheduled at', type: 'datetime-local' },
    ],
  },
  {
    title: 'Parties',
    fields: [
      { key: 'customer_id', label: 'Customer ID', type: 'number' },
      { key: 'customer_name', label: 'Customer name', type: 'text' },
      { key: 'driver_id', label: 'Driver ID', type: 'number' },
      { key: 'driver_name', label: 'Driver name', type: 'text' },
    ],
  },
  {
    title: 'Money (major units — ₦)',
    fields: [
      { key: 'initial_price', label: 'Initial price', type: 'number', cents: true },
      { key: 'agreed_price', label: 'Agreed price', type: 'number', cents: true },
      { key: 'payment_method', label: 'Payment method', type: 'select', options: ['Cash', 'MM', 'Visa'] },
      { key: 'payment_status', label: 'Payment status', type: 'select', options: ['unpaid', 'pending', 'paid', 'failed', 'refunded'] },
    ],
  },
  {
    title: 'Route',
    fields: [
      { key: 'pickup_address', label: 'Pickup address', type: 'text', wide: true },
      { key: 'pickup_lat', label: 'Pickup lat', type: 'text' },
      { key: 'pickup_lng', label: 'Pickup lng', type: 'text' },
      { key: 'dropoff_address', label: 'Drop-off address', type: 'text', wide: true },
      { key: 'dropoff_lat', label: 'Drop-off lat', type: 'text' },
      { key: 'dropoff_lng', label: 'Drop-off lng', type: 'text' },
    ],
  },
  {
    title: 'Notes',
    fields: [
      { key: 'cancelled_by', label: 'Cancelled by', type: 'text' },
      { key: 'cancel_reason', label: 'Cancel reason', type: 'text', wide: true },
      { key: 'schedule_note', label: 'Schedule note', type: 'text', wide: true },
      { key: 'details', label: 'Details', type: 'text', wide: true },
    ],
  },
];

function NegDrawer({ neg, onClose, onSaved, onAction }) {
  const [tab, setTab] = useState(0);
  const [form, setForm] = useState({});
  const [baseline, setBaseline] = useState({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    const f = {};
    EDIT_GROUPS.forEach((g) => g.fields.forEach((fd) => {
      let v = neg[fd.key];
      if (fd.cents) v = fromCents(v);
      if (fd.type === 'datetime-local' && v) v = String(v).replace(' ', 'T').slice(0, 16);
      f[fd.key] = v == null ? '' : String(v);
    }));
    setForm(f); setBaseline(f); setMsg(null);
  }, [neg]);

  const dirty = JSON.stringify(form) !== JSON.stringify(baseline);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const requestClose = () => {
    if (dirty && !window.confirm('You have unsaved changes. Discard them and close?')) return;
    onClose();
  };

  const save = async () => {
    setSaving(true); setMsg(null);
    try {
      // Send only what actually changed — a full-record write would stamp
      // blanks over fields this drawer doesn't show.
      const patch = {};
      Object.keys(form).forEach((k) => { if (form[k] !== baseline[k]) patch[k] = form[k]; });
      if (Object.keys(patch).length === 0) { setMsg({ type: 'error', text: 'Nothing changed' }); setSaving(false); return; }
      const { data } = await adminAPI.negotiationUpdate(neg.id, patch);
      if (data.code === 1) {
        setBaseline(form);
        setMsg({ type: 'success', text: `Saved ${Object.keys(patch).length} field(s)` });
        onSaved(data.data);
      } else {
        setMsg({ type: 'error', text: data.message || 'Save failed' });
      }
    } catch (e) {
      setMsg({ type: 'error', text: e?.response?.data?.message || 'Network error' });
    } finally { setSaving(false); }
  };

  const price = neg.fare != null ? neg.fare
    : (neg.agreed_price != null ? Number(neg.agreed_price) / 100 : Number(neg.initial_price || 0) / 100);

  const tabs = ['Details', 'Edit', 'Actions'];

  return (
    <div className="drawer-overlay">
      <div className="drawer-panel" style={{ width: 900, maxWidth: '96vw' }} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Negotiation #{neg.id}</h2>
          <span className={`badge badge-${neg.status?.toLowerCase()}`}>{neg.status}</span>
          {dirty && (
            <span style={{ fontSize: 11, fontWeight: 700, color: '#8a6100', background: '#fff3d6', border: '1px solid #f0d492', padding: '3px 8px', marginLeft: 8 }}>UNSAVED</span>
          )}
          <button className="drawer-close" onClick={requestClose}><FiX /></button>
        </div>

        <div style={{ display: 'flex', borderBottom: '1px solid #eee', flexShrink: 0 }}>
          {tabs.map((t, i) => (
            <button key={t} onClick={() => { setTab(i); setMsg(null); }}
              style={{
                padding: '10px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                border: 'none', background: 'none', color: tab === i ? '#040404' : '#999',
                borderBottom: tab === i ? '2px solid #EF9B11' : '2px solid transparent',
                marginBottom: -1, fontFamily: 'inherit',
              }}>{t}</button>
          ))}
        </div>

        <div className="drawer-body">
          {msg && (
            <div style={{
              padding: '10px 14px', marginBottom: 14, fontSize: 13,
              background: msg.type === 'success' ? '#e8f5e9' : '#ffebee',
              color: msg.type === 'success' ? '#388e3c' : '#d32f2f',
              border: `1px solid ${msg.type === 'success' ? '#c8e6c9' : '#ffcdd2'}`,
              display: 'flex', gap: 8, alignItems: 'center',
            }}>
              {msg.type === 'success' ? <FiCheck size={14} /> : <FiAlertTriangle size={14} />}{msg.text}
            </div>
          )}

          {tab === 0 && (
            <>
              <div className="d-section">
                <h4>Summary</h4>
                <div className="d-row"><span className="dk">Fare</span><span className="dv">{money(price)}</span></div>
                <div className="d-row"><span className="dk">Payment</span><span className="dv">{neg.payment_method || '—'} · {neg.payment_status || 'unpaid'}</span></div>
                <div className="d-row"><span className="dk">Source</span><span className="dv">{neg.ride_source || '—'}</span></div>
                <div className="d-row"><span className="dk">Created</span><span className="dv">{neg.created_at?.slice(0, 16) || '—'}</span></div>
                <div className="d-row"><span className="dk">Scheduled</span><span className="dv">{neg.scheduled_at || '—'}</span></div>
              </div>
              <div className="d-section">
                <h4>Route</h4>
                <div className="d-row"><span className="dk">Pickup</span><span className="dv">{neg.pickup_address || '—'}</span></div>
                <div className="d-row"><span className="dk">Drop-off</span><span className="dv">{neg.dropoff_address || '—'}</span></div>
              </div>
              <div className="d-section">
                <h4>Parties</h4>
                <div className="d-row"><span className="dk">Customer</span><span className="dv">{neg.customer_name || '—'} (#{neg.customer_id ?? '—'})</span></div>
                <div className="d-row"><span className="dk">Customer phone</span><span className="dv">{neg.customer_phone || '—'}</span></div>
                <div className="d-row"><span className="dk">Driver</span><span className="dv">{neg.driver_name || '—'} (#{neg.driver_id ?? '—'})</span></div>
                <div className="d-row"><span className="dk">Driver phone</span><span className="dv">{neg.driver_phone || '—'}</span></div>
              </div>
              {neg.records_list?.length > 0 && (
                <div className="d-section">
                  <h4>Price history ({neg.records_list.length})</h4>
                  {neg.records_list.map((r, i) => (
                    <div key={r.id || i} style={{ padding: '7px 0', borderBottom: '1px solid var(--grey-5)', fontSize: 12, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ color: 'var(--text-secondary)' }}>#{r.last_negotiator_id ?? '?'}</span>
                      <span style={{ fontWeight: 700 }}>{money(r.price != null ? Number(r.price) / 100 : null)}</span>
                      <span style={{ color: 'var(--text-tertiary)' }}>{r.created_at?.slice(0, 16)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === 1 && (
            <>
              {EDIT_GROUPS.map((g) => (
                <div className="d-section" key={g.title}>
                  <h4>{g.title}</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 14px' }}>
                    {g.fields.map((fd) => (
                      <div key={fd.key} style={{ gridColumn: fd.wide ? '1 / -1' : 'auto' }}>
                        <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>{fd.label}</label>
                        {fd.type === 'select' ? (
                          <select value={form[fd.key] ?? ''} onChange={(e) => set(fd.key, e.target.value)}
                            style={{ width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit', background: '#fff' }}>
                            <option value="">—</option>
                            {fd.options.map((o) => <option key={o} value={o}>{o}</option>)}
                          </select>
                        ) : (
                          <input type={fd.type === 'number' ? 'number' : fd.type} step={fd.type === 'number' ? 'any' : undefined}
                            value={form[fd.key] ?? ''} onChange={(e) => set(fd.key, e.target.value)}
                            style={{ width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' }} />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 4 }}>
                <button className="btn btn-sm" onClick={() => setForm(baseline)} disabled={!dirty || saving}>Revert</button>
                <button className="btn btn-sm btn-accent" onClick={save} disabled={saving || !dirty}>
                  <FiSave /> {saving ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            </>
          )}

          {tab === 2 && (
            <div className="d-section">
              <h4>Quick actions</h4>
              <p style={{ fontSize: 12, color: '#777' }}>
                These use the dedicated endpoints; anything else is on the Edit tab.
              </p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                {['Pending', 'Active', 'Accepted', 'Started', 'Completed', 'Cancelled'].map((s) => (
                  <button key={s} className="btn btn-sm" disabled={saving || neg.status === s}
                    onClick={() => onAction(neg.id, 'status', { status: s })}>{s}</button>
                ))}
              </div>
              <div style={{ marginTop: 14 }}>
                <button className="btn btn-sm btn-danger" disabled={saving || neg.status === 'Cancelled'}
                  onClick={() => onAction(neg.id, 'cancel')}><FiXCircle /> Cancel negotiation</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function NegotiationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // The query string is the source of truth, so refresh / back / a pasted
  // link all land on the same view — including the open record.
  const page    = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const search  = searchParams.get('q') || '';
  const filter  = searchParams.get('status') || '';
  const payFilter = searchParams.get('payment') || '';
  const openId  = searchParams.get('id') || '';
  const simOpen = searchParams.get('sim') === '1';

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [searchInput, setSearchInput] = useState(search);

  useEffect(() => { setSearchInput(search); }, [search]);

  const totalPages = Math.ceil(total / PER_PAGE);

  const patchParams = useCallback((patch, opts = {}) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      Object.entries(patch).forEach(([k, v]) => {
        if (v === '' || v == null) next.delete(k); else next.set(k, String(v));
      });
      return next;
    }, { replace: !!opts.replace });
  }, [setSearchParams]);

  const load = useCallback((p, q, f, pf) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: PER_PAGE };
    if (q) params.search = q;
    if (f) params.status = f;
    if (pf) params.payment_status = pf;
    adminAPI.negotiations(params)
      .then(({ data }) => {
        if (data.code === 1) { setItems(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load');
      })
      .catch((err) => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(page, search, filter, payFilter); }, [page, search, filter, payFilter, load]);

  // Keep the drawer in step with ?id= — including a deep link to a record
  // that isn't on this page of results.
  useEffect(() => {
    if (!openId) { setSelected(null); return; }
    if (selected && String(selected.id) === String(openId)) return;
    adminAPI.negotiationShow(openId)
      .then(({ data }) => { if (data.code === 1) setSelected(data.data); })
      .catch(() => {
        const local = items.find((n) => String(n.id) === String(openId));
        if (local) setSelected(local);
      });
  }, [openId, items]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = (item) => patchParams({ id: item.id });
  const closeDetail = () => patchParams({ id: '' });

  const refreshRow = (updated) => {
    setItems((prev) => prev.map((n) => (n.id === updated.id ? { ...n, ...updated } : n)));
  };

  const doAction = async (id, action, params = {}) => {
    try {
      if (action === 'status') await adminAPI.negotiationStatus(id, params);
      else if (action === 'cancel') await adminAPI.negotiationCancel(id);
      const { data } = await adminAPI.negotiationShow(id);
      if (data.code === 1) { setSelected(data.data); refreshRow(data.data); }
      load(page, search, filter, payFilter);
    } catch { /* surfaced by the drawer's own message area */ }
  };

  return (
    <div className="page-negotiations">
      {selected && (
        <NegDrawer neg={selected} onClose={closeDetail} onSaved={(u) => { setSelected(u); refreshRow(u); }} onAction={doAction} />
      )}
      {confirm && (
        <Confirm message={confirm.msg} onCancel={() => setConfirm(null)}
          onConfirm={() => { doAction(confirm.id, confirm.action); setConfirm(null); }} />
      )}
      {simOpen && (
        <React.Suspense fallback={null}>
          <RideSimulatorModal
            open
            onClose={() => patchParams({ sim: '' })}
            onCreated={() => load(page, search, filter, payFilter)}
          />
        </React.Suspense>
      )}

      <div className="page-toolbar">
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', width: '100%' }}>
          <div className="tab-bar" style={{ gap: 4 }}>
            {N_STATUSES.map((s) => (
              <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
                onClick={() => patchParams({ status: s, page: 1 })}>{s || 'All'}</button>
            ))}
          </div>
          <div className="tab-bar" style={{ gap: 4 }}>
            {PAY_FILTERS.map((pf) => (
              <button key={pf} className={`tab-btn ${payFilter === pf ? 'tab-btn--active' : ''}`}
                onClick={() => patchParams({ payment: pf, page: 1 })} style={{ fontSize: '0.78rem' }}>{pf || 'Any Payment'}</button>
            ))}
          </div>
          <div style={{ marginLeft: 'auto' }}>
            <button className="btn btn-sm btn-accent" onClick={() => patchParams({ sim: '1' })}
              title="Place a real order step by step, using the same API the app uses">
              <FiPlay /> Simulate an order
            </button>
          </div>
        </div>
      </div>

      <div className="page-toolbar" style={{ paddingTop: 0 }}>
        <form onSubmit={(e) => { e.preventDefault(); patchParams({ q: searchInput.trim(), page: 1 }); }} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search customer, driver, pickup, drop-off…" value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)} />
          <button type="submit" className="btn btn-sm">Search</button>
          {search && <button type="button" className="btn btn-sm" onClick={() => patchParams({ q: '', page: 1 })}>Clear</button>}
        </form>
        <span className="toolbar-info">{total} negotiations</span>
        <button className="btn btn-sm" onClick={() => load(page, search, filter, payFilter)} title="Reload"><FiRefreshCw /></button>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader">
          <span>{error}</span>
          <button className="btn btn-sm" onClick={() => load(page, search, filter, payFilter)} style={{ marginLeft: 8 }}>Retry</button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>Customer</th><th>Driver</th><th>Route</th>
                <th>Fare</th><th>Status</th><th>Payment</th><th>Date</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id}>
                  <td style={{ fontWeight: 700 }}>#{n.id}</td>
                  <td>{n.customer_name || (n.customer_id ? `#${n.customer_id}` : '—')}</td>
                  <td>{n.driver_name || (n.driver_id ? `#${n.driver_id}` : '—')}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {n.pickup_address || '?'} → {n.dropoff_address || '?'}
                  </td>
                  <td>{money(n.fare != null ? n.fare : (n.initial_price != null ? Number(n.initial_price) / 100 : null))}</td>
                  <td><span className={`badge badge-${n.status?.toLowerCase()}`}>{n.status}</span></td>
                  <td><span className={`badge badge-${n.payment_status === 'paid' ? 'success' : 'warning'}`}>{n.payment_status || 'unpaid'}</span></td>
                  <td>{n.created_at?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View / manage" onClick={() => openDetail(n)}><FiEye /></button>
                    {!['Completed', 'Cancelled'].includes(n.status) && (
                      <button className="btn btn-xs btn-danger" title="Cancel"
                        onClick={() => setConfirm({ id: n.id, action: 'cancel', msg: `Cancel negotiation #${n.id}?` })}><FiXCircle /></button>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No negotiations found</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => patchParams({ page: page - 1 })}><FiChevronLeft /></button>
          <span>Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => patchParams({ page: page + 1 })}><FiChevronRight /></button>
        </div>
      )}
    </div>
  );
}
