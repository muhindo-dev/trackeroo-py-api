import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiCheck, FiX, FiSearch } from 'react-icons/fi';

const STATUS_COLORS = { Verified: '#2e7d32', Pending: '#f59e0b', Rejected: '#f44336' };

export default function VehiclesPage() {
  const [items, setItems] = useState([]);
  const [allItems, setAllItems] = useState([]);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.vehicles(filter ? { verification_status: filter } : {})
      .then(({ data }) => { if (data.code === 1) { setAllItems(data.data || []); setItems(data.data || []); } else setError(data.message); })
      .catch((err) => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);

  useEffect(() => {
    if (!search.trim()) { setItems(allItems); return; }
    const q = search.toLowerCase();
    setItems(allItems.filter((v) => (v.reg_no || '').toLowerCase().includes(q) || (v.model || '').toLowerCase().includes(q)));
  }, [search, allItems]);

  const setStatus = async (id, verification_status) => {
    try { await adminAPI.vehicleVerify(id, { verification_status }); load(); } catch {}
  };

  return (
    <div className="page-vehicles">
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
            <h3 style={{ marginBottom: 10 }}>Log Book</h3>
            <img src={preview} alt="log book" style={{ width: '100%', borderRadius: 6 }} />
          </div>
        </div>
      )}
      <div className="page-toolbar">
        <form onSubmit={(e) => e.preventDefault()} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search reg no / model…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </form>
        <select className="d-input" style={{ maxWidth: 160 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="Pending">Pending</option>
          <option value="Verified">Verified</option>
          <option value="Rejected">Rejected</option>
        </select>
        <span className="toolbar-info">{items.length} vehicles</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Model</th><th>Reg No</th><th>Category</th><th>Colour</th><th>Driver</th><th>Log Book</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.id}>
                  <td style={{ fontWeight: 700 }}>#{v.id}</td>
                  <td>{v.model || v.type || '—'}</td>
                  <td>{v.reg_no || '—'}</td>
                  <td>{v.category_name || '—'}</td>
                  <td>{v.colour || '—'}</td>
                  <td>{v.driver_name || '—'}</td>
                  <td>{v.logbook_photo
                    ? <button className="btn btn-xs" onClick={() => setPreview(`/uploads/${v.logbook_photo}`)}>View</button>
                    : '—'}</td>
                  <td><span style={{ color: STATUS_COLORS[v.verification_status] || '#888', fontWeight: 600 }}>{v.verification_status}</span></td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Verify" onClick={() => setStatus(v.id, 'Verified')}><FiCheck /></button>
                    <button className="btn btn-xs btn-danger" title="Reject" onClick={() => setStatus(v.id, 'Rejected')}><FiX /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No vehicles found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
