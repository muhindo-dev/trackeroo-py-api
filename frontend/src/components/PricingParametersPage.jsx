import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiEdit2, FiX, FiSave, FiInfo } from 'react-icons/fi';

/**
 * How a fare is worked out:
 *
 *   Base fare
 * + Per extra km   × (distance − free km)
 * + Per minute     × trip minutes        (peak or off-peak rate)
 * + Waiting charges, if the driver waits longer than estimated
 * = Fare  (never below the Minimum fare)
 *
 * The old screen showed these as `q`, `r`, `s`, `t` — the letters from the
 * formula in the code. Nobody setting a price knows what `s` is, so every
 * field here is named for what it does and carries a one-line explanation.
 * It also left out `p` (per extra km), which is the number that most changes
 * what a rider pays.
 */
const SECTIONS = [
  {
    title: 'Core fare',
    hint: 'What every trip costs before time is counted.',
    fields: [
      ['base_rate_cad', 'Base fare', 'Charged on every trip, before distance or time.'],
      ['free_km', 'Free km included', 'Distance covered by the base fare. Only km beyond this are charged.'],
      ['p_extra_km', 'Price per extra km', 'Charged for each km beyond the free allowance.'],
      ['minimum_fare_cad', 'Minimum fare', 'The fare is never lower than this, however short the trip.'],
    ],
  },
  {
    title: 'Time charges',
    hint: 'Charged per minute of the trip. Peak rate applies inside the windows below.',
    fields: [
      ['q_peak_minute', 'Price per minute — peak', 'Used during the busy windows set below.'],
      ['r_offpeak_minute', 'Price per minute — off-peak', 'Used at every other time of day.'],
    ],
  },
  {
    title: 'Peak windows',
    hint: 'Hours of the day, 0–23, when the peak rate applies. Set both to 0 to disable a window.',
    fields: [
      ['peak_start_hour', 'Morning peak starts', 'Hour of day, e.g. 7 for 7am.'],
      ['peak_end_hour', 'Morning peak ends', 'Hour of day, e.g. 10 for 10am.'],
      ['peak_start_hour_pm', 'Evening peak starts', 'Hour of day, e.g. 16 for 4pm.'],
      ['peak_end_hour_pm', 'Evening peak ends', 'Hour of day, e.g. 20 for 8pm.'],
    ],
  },
  {
    title: 'Waiting charges',
    hint: 'Optional. Leave at 0 unless this service involves loading or unloading.',
    fields: [
      ['s_loading_overrun', 'Per minute waiting to load', 'Charged when pickup takes longer than estimated.'],
      ['t_completion_overrun', 'Per minute running late', 'Charged when the trip runs past its estimated finish.'],
    ],
  },
  {
    title: 'Surge',
    hint: 'Multiplies the whole fare. 1 means no surge.',
    fields: [
      ['surge_multiplier', 'Surge multiplier', '1 = normal. 1.5 = fares are 50% higher.'],
    ],
  },
];

const ALL_FIELDS = SECTIONS.flatMap((s) => s.fields.map(([k]) => k));

function RateDrawer({ rate, onClose, onSave }) {
  const [form, setForm] = useState({ ...rate });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setSaving(true); setErr('');
    try {
      const payload = {};
      ALL_FIELDS.forEach((k) => { payload[k] = form[k]; });
      await adminAPI.serviceRateUpdate(rate.id, payload);
      onSave();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  const cur = rate.currency || 'NGN';

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <div className="drawer-head">
          <h2>
            {rate.service_type}
            {rate.vehicle_type && rate.vehicle_type !== 'Any' && (
              <span style={{ fontWeight: 400, opacity: 0.7 }}> · {rate.vehicle_type}</span>
            )}
          </h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>

        <div className="drawer-body">
          <div style={{
            display: 'flex', gap: 8, padding: '10px 12px', marginBottom: 16,
            background: 'rgba(255,153,0,0.08)', border: '1px solid rgba(255,153,0,0.3)',
            fontSize: 12.5, lineHeight: 1.5,
          }}>
            <FiInfo style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              <strong>Fare</strong> = Base + (per km × km beyond the free allowance)
              + (per minute × trip minutes) + any waiting charges.
              Never less than the Minimum fare. All amounts in {cur}.
            </span>
          </div>

          {SECTIONS.map((section) => (
            <div key={section.title} style={{ marginBottom: 22 }}>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>{section.title}</div>
              <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 10 }}>{section.hint}</div>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {section.fields.map(([k, label, help]) => (
                  <div className="form-group" key={k}>
                    <label>{label}</label>
                    <input
                      className="d-input" type="number" step="any" min="0"
                      value={form[k] ?? ''}
                      onChange={(e) => set(k, e.target.value)}
                    />
                    <div style={{ fontSize: 11, opacity: 0.6, marginTop: 3, lineHeight: 1.4 }}>{help}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}

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

/** "7–10" for a real window, "—" when it is switched off. */
const win = (from, to) => (from || to ? `${from}:00–${to}:00` : '—');

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

      <div className="page-toolbar" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
        <span className="toolbar-info">{items.length} price lists</span>
        <span style={{ fontSize: 12, opacity: 0.65 }}>
          Fare = Base + per-km beyond the free allowance + per-minute for the trip, never below the minimum.
        </span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Service</th>
                <th>Base fare</th>
                <th>Free km</th>
                <th>Per extra km</th>
                <th>Per min (peak)</th>
                <th>Per min (off-peak)</th>
                <th>Peak windows</th>
                <th>Min fare</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 600 }}>
                    {r.service_type}
                    {/* Without this, two rows for the same service look like
                        duplicates when they are actually different vehicles. */}
                    {r.vehicle_type && r.vehicle_type !== 'Any' && (
                      <div style={{ fontWeight: 400, fontSize: 11.5, opacity: 0.6 }}>{r.vehicle_type}</div>
                    )}
                  </td>
                  <td>{r.base_rate}</td>
                  <td>{r.free_km}</td>
                  <td>{r.p_extra_km}</td>
                  <td>{r.q_peak_minute}</td>
                  <td>{r.r_offpeak_minute}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {win(r.peak_start_hour, r.peak_end_hour)}
                    <span style={{ opacity: 0.4 }}> · </span>
                    {win(r.peak_start_hour_pm, r.peak_end_hour_pm)}
                  </td>
                  <td>{r.minimum_fare}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Edit" onClick={() => setEditing(r)}><FiEdit2 /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No price lists found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
