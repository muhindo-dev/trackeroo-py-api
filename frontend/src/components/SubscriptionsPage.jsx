import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';

const STATUS_COLORS = { active: '#2e7d32', pending: '#f59e0b', expired: '#888', cancelled: '#f44336' };

export default function SubscriptionsPage() {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState({ active_count: 0, active_revenue: 0 });
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  const money = (v) => `₦${Number(v || 0).toLocaleString()}`;

  return (
    <div className="page-subscriptions">
      <div className="page-toolbar">
        <span className="toolbar-info">Active: <b>{stats.active_count}</b></span>
        <span className="toolbar-info">Active revenue: <b>{money(stats.active_revenue)}</b></span>
        <select className="d-input" style={{ maxWidth: 160 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="pending">Pending</option>
          <option value="expired">Expired</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Driver</th><th>Plan</th><th>Amount</th><th>Status</th><th>Start</th><th>End</th></tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 700 }}>#{s.id}</td>
                  <td>{s.driver_id}</td>
                  <td>{s.plan?.name || '—'}</td>
                  <td>{money(s.amount)}</td>
                  <td><span style={{ color: STATUS_COLORS[s.status] || '#888', fontWeight: 600 }}>{s.status}</span></td>
                  <td>{s.start_at ? new Date(s.start_at).toLocaleDateString() : '—'}</td>
                  <td>{s.end_at ? new Date(s.end_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="7" className="empty-state">No subscriptions found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
