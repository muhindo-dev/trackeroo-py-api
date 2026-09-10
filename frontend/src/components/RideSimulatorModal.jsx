import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FiXCircle, FiSearch, FiMapPin, FiCheck, FiChevronRight, FiChevronLeft,
  FiPlay, FiLoader, FiAlertTriangle, FiRefreshCw, FiUser, FiTruck,
} from 'react-icons/fi';
import { adminAPI, simAPI } from '../services/api';

const LocationPickerModal = React.lazy(() => import('./LocationPickerModal'));

/* Step-by-step order placement that drives the REAL mobile endpoints.
 *
 * Every call is made with an impersonation token for an actual user, so this
 * exercises the same code path a phone does — dispatch ranking, the offer
 * cascade, negotiation, cancellation. A simulator with its own private
 * shortcuts would pass while the app was broken, which is worse than useless.
 */

const STEPS = ['Who', 'Route', 'Ride', 'Launch', 'Live'];
const ACCENT = '#EF9B11';

const box = { width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' };
const label = { display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 };
const cap = { fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 10 };

const km = (a, b, c, d) => {
  if ([a, b, c, d].some((n) => n == null || Number.isNaN(n))) return 0;
  const R = 6371, r = Math.PI / 180;
  const dLa = (c - a) * r, dLo = (d - b) * r;
  const s = Math.sin(dLa / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
};

const errText = (e, fallback) =>
  e?.response?.data?.message || e?.message || fallback;

/* ── user picker ───────────────────────────────────────────────────────── */
function UserPicker({ userType, value, onPick, placeholder }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let dead = false;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const { data } = await adminAPI.users({ search: q, user_type: userType, per_page: 8, page: 1 });
        if (!dead) setRows(data.code === 1 ? (data.data?.data || []) : []);
      } catch { if (!dead) setRows([]); } finally { if (!dead) setBusy(false); }
    }, 300);
    return () => { dead = true; clearTimeout(t); };
  }, [q, userType]);

  return (
    <div>
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <FiSearch size={14} style={{ position: 'absolute', left: 10, top: '50%', marginTop: -7, color: '#999' }} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder}
          style={{ ...box, paddingLeft: 30 }} />
        {busy && <FiLoader size={13} style={{ position: 'absolute', right: 10, top: '50%', marginTop: -6, color: ACCENT, animation: 'spin .6s linear infinite' }} />}
      </div>
      <div style={{ border: '1px solid #eee', maxHeight: 190, overflowY: 'auto' }}>
        {rows.length === 0 && !busy && (
          <div style={{ padding: 12, fontSize: 12, color: '#999' }}>No {userType.toLowerCase()} matched.</div>
        )}
        {rows.map((u) => {
          const on = value?.id === u.id;
          return (
            <div key={u.id} onClick={() => onPick(u)}
              style={{
                padding: '9px 12px', fontSize: 12.5, cursor: 'pointer',
                borderBottom: '1px solid #f2f2f2',
                background: on ? '#fff6e6' : '#fff',
                borderLeft: on ? `3px solid ${ACCENT}` : '3px solid transparent',
              }}>
              <div style={{ fontWeight: 700 }}>
                {u.name || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.email} · #{u.id}
              </div>
              <div style={{ color: '#777', fontSize: 11.5 }}>
                {u.email || u.username}
                {userType === 'Driver' && (
                  <> · {u.ready_for_trip === 'Yes' ? 'online' : 'offline'}
                    {u.live_service_group ? ` · ${u.live_service_group}` : ''}</>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── main wizard ───────────────────────────────────────────────────────── */
export default function RideSimulatorModal({ open, onClose, onCreated }) {
  const [step, setStep] = useState(0);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const [customer, setCustomer] = useState(null);
  const [driver, setDriver] = useState(null);          // optional, for responding
  const [custToken, setCustToken] = useState('');
  const [drvToken, setDrvToken] = useState('');

  const [pickup, setPickup] = useState(null);          // {latitude, longitude, address}
  const [dropoff, setDropoff] = useState(null);
  const [picking, setPicking] = useState(null);        // 'pickup' | 'dropoff' | null

  const [cats, setCats] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [price, setPrice] = useState('');
  const [payment, setPayment] = useState('Cash');

  const [ride, setRide] = useState(null);              // dispatch payload
  const [status, setStatus] = useState(null);
  const [log, setLog] = useState([]);
  const pollRef = useRef(null);

  const say = useCallback((line, kind = 'info') => {
    setLog((l) => [{ t: new Date().toLocaleTimeString(), line, kind }, ...l].slice(0, 60));
  }, []);

  /* reset on open */
  useEffect(() => {
    if (!open) return;
    setStep(0); setErr(''); setBusy(false);
    setCustomer(null); setDriver(null); setCustToken(''); setDrvToken('');
    setPickup(null); setDropoff(null); setPicking(null);
    setCategoryId(''); setPrice(''); setPayment('Cash');
    setRide(null); setStatus(null); setLog([]);
    adminAPI.vehicleCategories()
      .then(({ data }) => setCats(data.code === 1 ? (data.data || []) : []))
      .catch(() => setCats([]));
  }, [open]);

  /* stop polling whenever we leave */
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);
  useEffect(() => { if (!open && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } }, [open]);

  const distance = pickup && dropoff
    ? km(pickup.latitude, pickup.longitude, dropoff.latitude, dropoff.longitude) : 0;

  /* ── step guards ─────────────────────────────────────────────────────── */
  const blocker = () => {
    if (step === 0 && !customer) return 'Choose the customer who will place this order.';
    if (step === 1 && (!pickup || !dropoff)) return 'Set both a pickup and a drop-off point.';
    if (step === 2) {
      if (!categoryId) return 'Choose a vehicle category.';
      const p = parseFloat(price);
      if (Number.isNaN(p) || p <= 0) return 'Enter the price the customer is offering.';
    }
    return '';
  };

  const next = () => {
    const b = blocker();
    if (b) { setErr(b); return; }
    setErr('');
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };
  const back = () => { setErr(''); setStep((s) => Math.max(s - 1, 0)); };

  /* ── launch ──────────────────────────────────────────────────────────── */
  const launch = async () => {
    setBusy(true); setErr('');
    try {
      say(`Minting a session token for ${customer.name || customer.email}…`);
      const { data: imp } = await simAPI.tokenFor(customer.id);
      const token = imp?.data?.token;
      if (!token) throw new Error(imp?.message || 'Could not impersonate that customer');
      setCustToken(token);

      const body = {
        category_id: Number(categoryId),
        distance_km: Number(distance.toFixed(2)),
        duration_min: Math.max(1, Math.round((distance / 25) * 60)),
        pickup_lat: pickup.latitude,
        pickup_lng: pickup.longitude,
        pickup_address: pickup.address || 'Simulated pickup',
        dropoff_lat: dropoff.latitude,
        dropoff_lng: dropoff.longitude,
        dropoff_address: dropoff.address || 'Simulated drop-off',
        payment_method: payment,
        proposed_price: Number(price),
      };
      say('POST /api/rides/request — the exact call the app makes.');
      const { data } = await simAPI.as(token).request(body);

      if (data.code !== 1) {
        // The commonest refusal is a ride already in flight; say so usefully.
        const active = data.data?.active_negotiation_id;
        setErr(active
          ? `${data.message} (ride #${active}) — cancel it first, or pick another customer.`
          : (data.message || 'The server refused the request'));
        say(data.message || 'Request refused', 'bad');
        setBusy(false);
        return;
      }

      const d = data.data?.dispatch || {};
      setRide(d);
      setStatus(data.data);
      say(`Ride #${d.negotiation_id} created · dispatch ${d.status} · candidates [${(d.candidates || []).join(', ') || 'none'}]`,
        d.status === 'no_match' ? 'warn' : 'good');

      if (driver) {
        try {
          const { data: di } = await simAPI.tokenFor(driver.id);
          if (di?.data?.token) { setDrvToken(di.data.token); say(`Driver token ready for ${driver.name || driver.email}.`); }
        } catch { say('Could not mint the driver token — driver actions disabled.', 'warn'); }
      }

      setStep(4);
      if (onCreated) onCreated(d.negotiation_id);
    } catch (e) {
      const m = errText(e, 'The request failed');
      setErr(m); say(m, 'bad');
    } finally { setBusy(false); }
  };

  /* ── live polling ────────────────────────────────────────────────────── */
  const refresh = useCallback(async () => {
    if (!ride?.negotiation_id || !custToken) return;
    try {
      const { data } = await simAPI.as(custToken).status(ride.negotiation_id);
      if (data.code === 1) setStatus(data.data);
    } catch { /* a failed poll must never break the panel */ }
  }, [ride, custToken]);

  useEffect(() => {
    if (step !== 4 || !ride?.negotiation_id) return undefined;
    refresh();
    pollRef.current = setInterval(refresh, 3000);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [step, ride, refresh]);

  const act = async (fn, describe) => {
    setBusy(true); setErr('');
    try {
      const { data } = await fn();
      say(`${describe}: ${data.message || (data.code === 1 ? 'ok' : 'refused')}`,
        data.code === 1 ? 'good' : 'warn');
      await refresh();
    } catch (e) {
      const m = errText(e, `${describe} failed`);
      setErr(m); say(m, 'bad');
    } finally { setBusy(false); }
  };

  if (!open) return null;

  const dispatchStatus = status?.dispatch_status || ride?.status || '—';
  const neg = status?.negotiation || {};

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 2500, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14 }}>
      <div style={{ width: 1180, maxWidth: '97vw', height: '92vh', minHeight: 520, background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 12px 48px rgba(0,0,0,0.35)' }}>

        {/* header + stepper */}
        <div style={{ padding: '14px 18px', borderBottom: '2px solid #040404', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <FiPlay size={17} />
            <div style={{ flex: 1, fontWeight: 700, fontSize: 15 }}>Place a test order — live system</div>
            <button onClick={onClose} title="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#666', padding: 4 }}>
              <FiXCircle size={20} />
            </button>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {STEPS.map((s, i) => (
              <div key={s} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 7 }}>
                <div style={{
                  width: 22, height: 22, flexShrink: 0, borderRadius: '50%', fontSize: 11, fontWeight: 800,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: i < step ? '#388e3c' : i === step ? ACCENT : '#eee',
                  color: i <= step ? '#fff' : '#999',
                }}>{i < step ? <FiCheck size={12} /> : i + 1}</div>
                <div style={{ fontSize: 12, fontWeight: i === step ? 800 : 600, color: i === step ? '#040404' : '#999' }}>{s}</div>
                {i < STEPS.length - 1 && <div style={{ flex: 1, height: 2, background: i < step ? '#388e3c' : '#eee' }} />}
              </div>
            ))}
          </div>
        </div>

        {/* body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 18, minHeight: 0 }}>
          {err && (
            <div style={{ padding: '10px 14px', marginBottom: 14, fontSize: 13, background: '#ffebee', color: '#d32f2f', border: '1px solid #ffcdd2', display: 'flex', gap: 8, alignItems: 'center' }}>
              <FiAlertTriangle size={14} /> {err}
            </div>
          )}

          {step === 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22 }}>
              <div>
                <div style={cap}><FiUser size={11} style={{ marginRight: 5 }} />Customer (required)</div>
                <p style={{ fontSize: 12, color: '#777', marginTop: 0 }}>
                  The order is placed as this real account, using their own session token.
                </p>
                <UserPicker userType="Customer" value={customer} onPick={setCustomer} placeholder="Search customers…" />
              </div>
              <div>
                <div style={cap}><FiTruck size={11} style={{ marginRight: 5 }} />Driver to act as (optional)</div>
                <p style={{ fontSize: 12, color: '#777', marginTop: 0 }}>
                  Pick one to accept, negotiate or decline from this panel. Dispatch still
                  chooses who gets the offer — this only lets you answer as them.
                </p>
                <UserPicker userType="Driver" value={driver} onPick={setDriver} placeholder="Search drivers…" />
              </div>
            </div>
          )}

          {step === 1 && (
            <div>
              <div style={cap}>Route</div>
              {[['pickup', 'Pickup', pickup], ['dropoff', 'Drop-off', dropoff]].map(([key, name, val]) => (
                <div key={key} style={{ border: '1.5px solid #e6e6e6', background: '#fafafa', padding: 14, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#666', marginBottom: 3 }}>{name}</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: val ? '#040404' : '#999' }}>
                      {val ? `${Number(val.latitude).toFixed(6)}, ${Number(val.longitude).toFixed(6)}` : 'Not set'}
                    </div>
                    {val?.address && <div style={{ fontSize: 12, color: '#777', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{val.address}</div>}
                  </div>
                  <button className="btn btn-sm btn-primary" onClick={() => setPicking(key)} style={{ height: 38, flexShrink: 0 }}>
                    <FiMapPin size={14} /> {val ? 'Change' : 'Pick on map'}
                  </button>
                </div>
              ))}
              {pickup && dropoff && (
                <div style={{ fontSize: 13, fontWeight: 700, color: '#388e3c' }}>
                  Straight-line distance ≈ {distance.toFixed(2)} km
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
              <div>
                <label style={label}>Vehicle category</label>
                <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} style={{ ...box, background: '#fff' }}>
                  <option value="">Choose…</option>
                  {cats.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}{c.service_group ? ` — ${c.service_group}` : ''}
                    </option>
                  ))}
                </select>
                <p style={{ fontSize: 12, color: '#777' }}>
                  Dispatch only considers drivers live for this category's service group.
                </p>
              </div>
              <div>
                <label style={label}>Price the customer offers</label>
                <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="e.g. 1500" style={box} />
                <label style={{ ...label, marginTop: 12 }}>Payment method</label>
                <select value={payment} onChange={(e) => setPayment(e.target.value)} style={{ ...box, background: '#fff' }}>
                  {['Cash', 'MM', 'Visa'].map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <div style={cap}>Review</div>
              <div style={{ border: '1.5px solid #e6e6e6', background: '#fafafa', padding: 16 }}>
                {[
                  ['Customer', customer ? `${customer.name || customer.email} · #${customer.id}` : '—'],
                  ['Acting driver', driver ? `${driver.name || driver.email} · #${driver.id}` : 'none (watch only)'],
                  ['Pickup', pickup?.address || `${pickup?.latitude}, ${pickup?.longitude}`],
                  ['Drop-off', dropoff?.address || `${dropoff?.latitude}, ${dropoff?.longitude}`],
                  ['Distance', `${distance.toFixed(2)} km`],
                  ['Category', cats.find((c) => String(c.id) === String(categoryId))?.name || categoryId],
                  ['Price', price],
                  ['Payment', payment],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid #eee', fontSize: 13 }}>
                    <div style={{ width: 130, color: '#777', fontWeight: 600, flexShrink: 0 }}>{k}</div>
                    <div style={{ fontWeight: 700, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{v}</div>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 12.5, color: '#777' }}>
                This creates a <b>real ride</b> on the live system as this customer — the same
                request the mobile app sends. Cancel it from the next step when you're done.
              </p>
            </div>
          )}

          {step === 4 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
              <div>
                <div style={cap}>Live dispatch</div>
                <div style={{ border: '1.5px solid #e6e6e6', background: '#fafafa', padding: 14, marginBottom: 12 }}>
                  {[
                    ['Ride', ride?.negotiation_id ? `#${ride.negotiation_id}` : '—'],
                    ['Dispatch', dispatchStatus],
                    ['Ride status', neg.status || '—'],
                    ['Driver', neg.driver_id ? `#${neg.driver_id} ${neg.driver_name || ''}` : 'unassigned'],
                    ['Fare on table', neg.fare != null ? neg.fare : '—'],
                    ['Agreed', neg.agreed_price ? 'yes' : 'not yet'],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', padding: '5px 0', fontSize: 13, borderBottom: '1px solid #eee' }}>
                      <div style={{ width: 110, color: '#777', fontWeight: 600 }}>{k}</div>
                      <div style={{ fontWeight: 700 }}>{String(v)}</div>
                    </div>
                  ))}
                </div>

                <div style={cap}>Customer actions</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                  <button className="btn btn-sm btn-secondary" disabled={busy} onClick={refresh}><FiRefreshCw size={13} /> Refresh</button>
                  <button className="btn btn-sm btn-secondary" disabled={busy || dispatchStatus !== 'no_match'}
                    onClick={() => act(() => simAPI.as(custToken).retry(ride.negotiation_id), 'Search again')}>Search again</button>
                  <button className="btn btn-sm btn-secondary" disabled={busy}
                    onClick={() => act(() => simAPI.as(custToken).cancel(ride.negotiation_id), 'Cancel ride')}>Cancel ride</button>
                </div>

                <div style={cap}>Driver actions {driver ? `— as ${driver.name || driver.email}` : ''}</div>
                {!drvToken ? (
                  <p style={{ fontSize: 12, color: '#999' }}>
                    No driver selected on step 1, so there is nobody to answer as.
                  </p>
                ) : (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {['accept', 'negotiate', 'decline'].map((a) => (
                      <button key={a} className={`btn btn-sm ${a === 'accept' ? 'btn-primary' : 'btn-secondary'}`}
                        disabled={busy}
                        onClick={() => act(() => simAPI.as(drvToken).respond(ride.negotiation_id, a), `Driver ${a}`)}
                        style={a === 'accept' ? { background: '#388e3c', borderColor: '#388e3c' } : undefined}>
                        {a[0].toUpperCase() + a.slice(1)}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ minWidth: 0 }}>
                <div style={cap}>Activity</div>
                <div style={{ border: '1px solid #eee', height: '100%', maxHeight: 430, overflowY: 'auto', background: '#fcfcfc' }}>
                  {log.length === 0 && <div style={{ padding: 12, fontSize: 12, color: '#999' }}>Nothing yet.</div>}
                  {log.map((l, i) => (
                    <div key={i} style={{
                      padding: '7px 11px', fontSize: 12, borderBottom: '1px solid #f2f2f2',
                      color: l.kind === 'bad' ? '#d32f2f' : l.kind === 'warn' ? '#8a6100' : l.kind === 'good' ? '#2e7d32' : '#444',
                    }}>
                      <span style={{ color: '#aaa', marginRight: 7, fontFamily: 'monospace' }}>{l.t}</span>{l.line}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* footer */}
        <div style={{ borderTop: '1px solid #eee', padding: '12px 18px', display: 'flex', gap: 8, justifyContent: 'space-between', flexShrink: 0, background: '#fafafa' }}>
          <button className="btn btn-sm btn-secondary" onClick={back} disabled={step === 0 || step === 4 || busy}>
            <FiChevronLeft size={14} /> Back
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm btn-secondary" onClick={onClose}>Close</button>
            {step < 3 && (
              <button className="btn btn-sm btn-primary" onClick={next} disabled={busy}>
                Next <FiChevronRight size={14} />
              </button>
            )}
            {step === 3 && (
              <button className="btn btn-sm btn-primary" onClick={launch} disabled={busy}
                style={{ background: '#388e3c', borderColor: '#388e3c' }}>
                {busy ? 'Placing…' : <><FiPlay size={13} /> Place the order</>}
              </button>
            )}
          </div>
        </div>
      </div>

      {picking && (
        <React.Suspense fallback={null}>
          <LocationPickerModal
            open
            initial={picking === 'pickup' ? pickup : dropoff}
            defaultCenter={[6.5250, 3.3800]}
            countryCodes="ng,ug"
            title={picking === 'pickup' ? 'Set the pickup point' : 'Set the drop-off point'}
            onCancel={() => setPicking(null)}
            onConfirm={(loc) => {
              if (picking === 'pickup') setPickup(loc); else setDropoff(loc);
              setPicking(null); setErr('');
            }}
          />
        </React.Suspense>
      )}
    </div>
  );
}
