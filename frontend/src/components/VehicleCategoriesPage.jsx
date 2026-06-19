import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiPlus, FiEdit2, FiTrash2, FiX, FiAlertTriangle, FiSave, FiSearch } from 'react-icons/fi';

const EMPTY = {
  name: '', code: '', service_group: 'Truck', wheels: '', description: '',
  min_price: '', est_loading_minutes: '', per_km_rate: '', is_luxury: false, sort_order: '',
};

const GROUPS = ['Truck', 'Special Hire', 'Boda'];

function Confirm({ message, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 16 }}>
          <FiAlertTriangle size={22} color="#f44336" style={{ flexShrink: 0, marginTop: 2 }} />
          <p>{message}</p>
        </div>
        <div className="modal-actions">
          <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
          <button className="btn btn-sm btn-danger" onClick={onConfirm}>Deactivate</button>
        </div>
      </div>
    </div>
  );
}

function CategoryDrawer({ item, onClose, onSave }) {
  const [form, setForm] = useState(item ? { ...item } : { ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }));
  const isNew = !item;

  const save = async () => {
    if (!form.name?.trim()) { setErr('Name is required'); return; }
    if (!form.code?.trim()) { setErr('Code is required (e.g. small_truck)'); return; }
    setSaving(true); setErr('');
    try {
      if (isNew) await adminAPI.vehicleCategoryCreate(form);
      else await adminAPI.vehicleCategoryUpdate(item.id, form);
      onSave();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <div className="drawer-head">
          <h2>{isNew ? 'New Vehicle Category' : `Edit: ${item.name}`}</h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label>Name *</label>
              <input className="d-input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Small Truck" />
            </div>
            <div className="form-group">
              <label>Code *</label>
              <input className="d-input" value={form.code} onChange={e => set('code', e.target.value)} placeholder="e.g. small_truck" disabled={!isNew} />
            </div>
            <div className="form-group">
              <label>Service Group</label>
              <select className="d-input" value={form.service_group} onChange={e => set('service_group', e.target.value)}>
                {GROUPS.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Wheels</label>
              <input className="d-input" type="number" value={form.wheels} onChange={e => set('wheels', e.target.value)} placeholder="e.g. 4" />
            </div>
            <div className="form-group">
              <label>Minimum Price (Base) ₦</label>
              <input className="d-input" type="number" step="any" value={form.min_price} onChange={e => set('min_price', e.target.value)} placeholder="e.g. 15000" />
            </div>
            <div className="form-group">
              <label>Est. Loading Time (min)</label>
              <input className="d-input" type="number" value={form.est_loading_minutes} onChange={e => set('est_loading_minutes', e.target.value)} placeholder="e.g. 20" />
            </div>
            <div className="form-group">
              <label>Per-Km Rate ₦ (p)</label>
              <input className="d-input" type="number" step="any" value={form.per_km_rate} onChange={e => set('per_km_rate', e.target.value)} placeholder="e.g. 400" />
            </div>
            <div className="form-group">
              <label>Sort Order</label>
              <input className="d-input" type="number" value={form.sort_order} onChange={e => set('sort_order', e.target.value)} placeholder="e.g. 10" />
            </div>
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="checkbox" checked={!!form.is_luxury} onChange={e => set('is_luxury', e.target.checked)} />
                Luxury (for Special Hire luxury cars)
              </label>
            </div>
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label>Description</label>
              <textarea className="d-textarea" value={form.description || ''} onChange={e => set('description', e.target.value)} rows={2} placeholder="Optional notes…" />
            </div>
          </div>
          {err && <p style={{ color: 'var(--error)', fontSize: 13, marginTop: 10 }}>{err}</p>}
        </div>
        <div className="drawer-footer">
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save} style={{ flex: 1 }}>
            <FiSave /> {saving ? 'Saving…' : isNew ? 'Create Category' : 'Save Changes'}
          </button>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function VehicleCategoriesPage() {
  const [items, setItems] = useState([]);
  const [allItems, setAllItems] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [confirm, setConfirm] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.vehicleCategories()
      .then(({ data }) => {
        if (data.code === 1) { setAllItems(data.data || []); setItems(data.data || []); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!search.trim()) { setItems(allItems); return; }
    const q = search.toLowerCase();
    setItems(allItems.filter(s => (s.name || '').toLowerCase().includes(q) || (s.service_group || '').toLowerCase().includes(q)));
  }, [search, allItems]);

  const doDelete = async id => {
    try { await adminAPI.vehicleCategoryDelete(id); load(); } catch {}
  };

  const money = v => v ? `₦${Number(v).toLocaleString()}` : '—';

  return (
    <div className="page-vehicle-categories">
      {editing !== null && (
        <CategoryDrawer item={editing || null} onClose={() => setEditing(null)} onSave={() => { setEditing(null); load(); }} />
      )}
      {confirm && (
        <Confirm
          message={`Deactivate category "${confirm.name}"?`}
          onCancel={() => setConfirm(null)}
          onConfirm={() => { doDelete(confirm.id); setConfirm(null); }}
        />
      )}

      <div className="page-toolbar">
        <form onSubmit={e => e.preventDefault()} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search by name or group…" value={search} onChange={e => setSearch(e.target.value)} />
        </form>
        <span className="toolbar-info">{items.length} of {allItems.length} categories</span>
        <button className="btn btn-sm btn-accent" onClick={() => setEditing(false)}><FiPlus /> Add Category</button>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Name</th><th>Group</th><th>Wheels</th><th>Min Price</th><th>Loading</th><th>Per Km</th><th>Luxury</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map(s => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 700 }}>#{s.id}</td>
                  <td style={{ fontWeight: 600 }}>{s.name || '—'}</td>
                  <td>{s.service_group || '—'}</td>
                  <td>{s.wheels || '—'}</td>
                  <td>{money(s.min_price)}</td>
                  <td>{s.est_loading_minutes ? `${s.est_loading_minutes} min` : '—'}</td>
                  <td>{money(s.per_km_rate)}</td>
                  <td>{s.is_luxury ? '✦' : '—'}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Edit" onClick={() => setEditing(s)}><FiEdit2 /></button>
                    <button className="btn btn-xs btn-danger" title="Deactivate" onClick={() => setConfirm(s)}><FiTrash2 /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No vehicle categories found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
