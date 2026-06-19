import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiEdit2, FiX, FiSave } from 'react-icons/fi';

/// Edit the pricing-formula coefficients per service group:
/// PRICE = base + p·extra_km + q·peak + r·offpeak + s·loading + t·completion
const FIELDS = [
  ['base_rate_cad', 'Base'],
  ['p_extra_km', 'p · extra km'],
  ['q_peak_minute', 'q · peak min'],
  ['r_offpeak_minute', 'r · off-peak min'],
  ['s_loading_overrun', 's · loading overrun'],
  ['t_completion_overrun', 't · completion overrun'],
  ['free_km', 'Free km'],
  ['surge_multiplier', 'Surge ×'],
  ['minimum_fare_cad', 'Minimum fare'],
  ['peak_start_hour', 'Peak start (AM)'],
  ['peak_end_hour', 'Peak end (AM)'],
  ['peak_start_hour_pm', 'Peak start (PM)'],
  ['peak_end_hour_pm', 'Peak end (PM)'],
];

function RateDrawer({ rate, onClose, onSave }) {
  const [form, setForm] = useState({ ...rate });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setSaving(true); setErr('');
    try {
      const payload = {};
      FIELDS.forEach(([k]) => { payload[k] = form[k]; });
      await adminAPI.serviceRateUpdate(rate.id, payload);
      onSave();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div className="drawer-head">
          <h2>Pricing — {rate.service_type}</h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {FIELDS.map(([k, label]) => (
              <div className="form-group" key={k}>
                <label>{label}</label>
                <input className="d-input" type="number" step="any"
                  value={form[k] ?? ''} onChange={(e) => set(k, e.target.value)} />
              </div>
            ))}
          </div>
          {err && <p style={{ color: 'var(--error)', fontSize: 13, marginTop: 10 }}>{err}</p>}
        </div>
        <div className="drawer-footer">
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save} style={{ flex: 1 }}>
            <FiSave /> {saving ? 'Saving…' : 'Save Changes'}
          </button>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function PricingParametersPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.serviceRates()
      .then(({ data }) => { if (data.code === 1) setItems(data.data || []); else setError(data.message); })
      .catch((err) => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="page-pricing">
      {editing && <RateDrawer rate={editing} onClose={() => setEditing(null)} onSave={() => { setEditing(null); load(); }} />}
      <div className="page-toolbar">
        <span className="toolbar-info">{items.length} service groups</span>
      </div>
      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Service</th><th>Base</th><th>q</th><th>r</th><th>s</th><th>t</th><th>Peak AM</th><th>Peak PM</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 600 }}>{r.service_type}</td>
                  <td>{r.base_rate}</td>
                  <td>{r.q_peak_minute}</td>
                  <td>{r.r_offpeak_minute}</td>
                  <td>{r.s_loading_overrun}</td>
                  <td>{r.t_completion_overrun}</td>
                  <td>{r.peak_start_hour}–{r.peak_end_hour}</td>
                  <td>{r.peak_start_hour_pm}–{r.peak_end_hour_pm}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Edit" onClick={() => setEditing(r)}><FiEdit2 /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No service rates found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
