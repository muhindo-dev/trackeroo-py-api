import React, { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { FiSearch, FiXCircle, FiCheck, FiCrosshair, FiMapPin, FiLoader } from 'react-icons/fi';

/* Reusable map location picker.
 *
 * Search a place, drop / drag a pin, or type exact coordinates — then confirm.
 * Uses OpenStreetMap tiles + Nominatim, so it needs no API key (the Google key
 * we have has Geocoding disabled).
 *
 * Props:
 *   open          bool
 *   initial       { latitude, longitude } | null  — pin starts here
 *   defaultCenter [lat, lng]                      — map centre when there's no pin
 *   title         string
 *   onCancel()
 *   onConfirm({ latitude, longitude, address })
 */

const ACCENT = '#EF9B11';
const NOMINATIM = 'https://nominatim.openstreetmap.org';

// Inline SVG pin — avoids Leaflet's bundler-broken default marker images.
const pinIcon = L.divIcon({
  className: 'lp-pin',
  html: `<svg width="30" height="42" viewBox="0 0 30 42" xmlns="http://www.w3.org/2000/svg">
    <path d="M15 0C6.7 0 0 6.7 0 15c0 11 15 27 15 27s15-16 15-27c0-8.3-6.7-15-15-15z" fill="${ACCENT}" stroke="#040404" stroke-width="2"/>
    <circle cx="15" cy="15" r="5.5" fill="#040404"/>
  </svg>`,
  iconSize: [30, 42],
  iconAnchor: [15, 42],
});

const fmt = (n) => (n == null || Number.isNaN(n) ? '' : Number(n).toFixed(6));

export default function LocationPickerModal({
  open,
  initial,
  defaultCenter = [6.5250, 3.3800],
  countryCodes = '',            // e.g. 'ng,ug' — biases + speeds up search a lot
  title = 'Pick a location',
  onCancel,
  onConfirm,
}) {
  const mapElRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const cacheRef = useRef(new Map());

  const [pos, setPos] = useState(null);          // { lat, lng }
  const [address, setAddress] = useState('');
  const [resolving, setResolving] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [noHits, setNoHits] = useState(false);
  const [err, setErr] = useState('');
  const [latText, setLatText] = useState('');
  const [lngText, setLngText] = useState('');

  /* ── reverse geocode (pin -> address) ─────────────────────────────── */
  const reverse = useCallback(async (lat, lng) => {
    setResolving(true);
    try {
      const r = await fetch(`${NOMINATIM}/reverse?format=jsonv2&lat=${lat}&lon=${lng}`, {
        headers: { Accept: 'application/json' },
      });
      const j = await r.json();
      setAddress(j?.display_name || '');
    } catch {
      setAddress('');
    } finally {
      setResolving(false);
    }
  }, []);

  /* ── move the pin (single source of truth) ────────────────────────── */
  const placePin = useCallback((lat, lng, { fly = false } = {}) => {
    setPos({ lat, lng });
    setLatText(fmt(lat));
    setLngText(fmt(lng));
    setErr('');
    const map = mapRef.current;
    if (map) {
      if (markerRef.current) markerRef.current.setLatLng([lat, lng]);
      if (fly) map.flyTo([lat, lng], Math.max(map.getZoom(), 15), { duration: 0.6 });
    }
    reverse(lat, lng);
  }, [reverse]);

  /* ── build / tear down the map when the modal opens ───────────────── */
  useEffect(() => {
    if (!open) return undefined;

    const start = initial?.latitude != null && initial?.longitude != null
      ? [Number(initial.latitude), Number(initial.longitude)]
      : null;

    // Defer one frame so the container has real dimensions before Leaflet reads them.
    const raf = requestAnimationFrame(() => {
      if (!mapElRef.current || mapRef.current) return;

      const map = L.map(mapElRef.current, { zoomControl: true, attributionControl: true })
        .setView(start || defaultCenter, start ? 15 : 12);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(map);

      const marker = L.marker(start || defaultCenter, { draggable: true, icon: pinIcon }).addTo(map);
      marker.on('dragend', () => {
        const { lat, lng } = marker.getLatLng();
        placePin(lat, lng);
      });
      map.on('click', (e) => placePin(e.latlng.lat, e.latlng.lng));

      mapRef.current = map;
      markerRef.current = marker;

      // Modals commonly render the map grey without this.
      setTimeout(() => map.invalidateSize(), 60);

      if (start) placePin(start[0], start[1]);
    });

    return () => {
      cancelAnimationFrame(raf);
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        markerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /* reset transient state each time it opens */
  useEffect(() => {
    if (!open) {
      setResults([]); setQuery(''); setErr(''); setAddress(''); setPos(null); setNoHits(false);
      setLatText(''); setLngText('');
    }
  }, [open]);

  /* ── debounced place search ───────────────────────────────────────── */
  useEffect(() => {
    if (!open) return undefined;
    const q = query.trim();
    if (q.length < 3) { setResults([]); setSearching(false); setNoHits(false); return undefined; }

    // Serve repeats instantly — retyping/backspacing shouldn't re-hit the network.
    const cached = cacheRef.current.get(q.toLowerCase());
    if (cached) { setResults(cached); setNoHits(cached.length === 0); setSearching(false); return undefined; }

    // Show the spinner during the debounce too, so typing feels answered immediately.
    setSearching(true);
    setNoHits(false);

    const ctl = new AbortController();
    // Hard ceiling: a hung Nominatim must not spin forever.
    const killer = setTimeout(() => ctl.abort(), 8000);

    const t = setTimeout(async () => {
      try {
        const cc = countryCodes ? `&countrycodes=${countryCodes}` : '';
        const r = await fetch(
          `${NOMINATIM}/search?format=jsonv2&limit=8&addressdetails=0${cc}&q=${encodeURIComponent(q)}`,
          { headers: { Accept: 'application/json' }, signal: ctl.signal },
        );
        const json = (await r.json()) || [];
        cacheRef.current.set(q.toLowerCase(), json);
        setResults(json);
        setNoHits(json.length === 0);
        setErr('');
      } catch (e) {
        if (e.name === 'AbortError') return;      // superseded or timed out; leave UI alone
        setResults([]);
        setErr('Search is unavailable right now — you can still click the map or type coordinates.');
      } finally {
        clearTimeout(killer);
        setSearching(false);
      }
    }, 350);

    return () => { clearTimeout(t); clearTimeout(killer); ctl.abort(); };
  }, [query, open, countryCodes]);

  const useMyLocation = () => {
    if (!navigator.geolocation) { setErr('This browser has no geolocation'); return; }
    setErr('');
    navigator.geolocation.getCurrentPosition(
      (p) => placePin(p.coords.latitude, p.coords.longitude, { fly: true }),
      (e) => setErr(
        e.code === 1 ? 'Location permission was denied for this site.'
          : e.code === 3 ? 'Locating timed out. Search for the place instead, or click the map.'
            : 'This device could not report a location (common on desktops). Search or click the map instead.',
      ),
      // Desktops have no GPS; high accuracy just guarantees kCLErrorLocationUnknown.
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 },
    );
  };

  const applyTyped = () => {
    const la = parseFloat(latText), ln = parseFloat(lngText);
    if (Number.isNaN(la) || Number.isNaN(ln)) { setErr('Enter valid numbers for latitude and longitude'); return; }
    if (la < -90 || la > 90 || ln < -180 || ln > 180) { setErr('Coordinates are out of range'); return; }
    placePin(la, ln, { fly: true });
  };

  if (!open) return null;

  const label = { display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 };
  const input = { width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' };

  return (
    // Deliberately no backdrop-click-to-close: this must not vanish mid-edit.
    <div style={{ position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <div style={{ width: 1000, maxWidth: '96vw', height: '86vh', background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 12px 48px rgba(0,0,0,0.3)' }}>

        {/* header */}
        <div style={{ padding: '14px 18px', borderBottom: '2px solid #040404', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <FiMapPin size={18} />
          <div style={{ flex: 1, fontWeight: 700, fontSize: 15 }}>{title}</div>
          <button onClick={onCancel} title="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#666', padding: 4 }}>
            <FiXCircle size={20} />
          </button>
        </div>

        {/* search */}
        <div style={{ padding: '12px 18px', borderBottom: '1px solid #eee', flexShrink: 0, position: 'relative', zIndex: 1200, background: '#fff' }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <FiSearch size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#999' }} />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search a place, street, town or landmark…"
                style={{ ...input, paddingLeft: 30 }}
              />
              {searching && (
                <FiLoader
                  size={14}
                  style={{ position: 'absolute', right: 10, top: '50%', marginTop: -7, color: '#EF9B11', animation: 'spin .6s linear infinite' }}
                />
              )}
            </div>
            <button className="btn btn-sm btn-secondary" onClick={useMyLocation} style={{ height: 38, flexShrink: 0, whiteSpace: 'nowrap' }}>
              <FiCrosshair size={14} /> My location
            </button>
          </div>

          {(searching || noHits || results.length > 0) && query.trim().length >= 3 && (
            <div style={{ position: 'absolute', left: 18, right: 18, top: '100%', background: '#fff', border: '1.5px solid #ccc', borderTop: 'none', maxHeight: 260, overflowY: 'auto', zIndex: 1210, boxShadow: '0 6px 18px rgba(0,0,0,0.12)' }}>
              {searching && (
                <div style={{ padding: '10px 12px', fontSize: 12.5, color: '#777', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FiLoader size={13} style={{ animation: 'spin .6s linear infinite', color: '#EF9B11' }} />
                  Searching places…
                </div>
              )}
              {!searching && noHits && (
                <div style={{ padding: '10px 12px', fontSize: 12.5, color: '#777' }}>
                  No place matched “{query.trim()}”. Try a nearby town, or click the map directly.
                </div>
              )}
              {results.map((r) => (
                <div
                  key={r.place_id}
                  onClick={() => { placePin(parseFloat(r.lat), parseFloat(r.lon), { fly: true }); setResults([]); setQuery(r.display_name.split(',')[0]); }}
                  style={{ padding: '9px 12px', fontSize: 12.5, borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#faf6ee'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = '#fff'; }}
                >
                  {r.display_name}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* map */}
        <div style={{ flex: 1, position: 'relative', minHeight: 0, zIndex: 0 }}>
          <div ref={mapElRef} style={{ position: 'absolute', inset: 0 }} />
          <div style={{ position: 'absolute', left: 12, bottom: 12, zIndex: 500, background: 'rgba(255,255,255,0.95)', border: '1px solid #ddd', padding: '6px 10px', fontSize: 11.5, color: '#555', maxWidth: '70%' }}>
            Click the map or drag the pin to set the exact point.
          </div>
        </div>

        {/* footer */}
        <div style={{ borderTop: '1px solid #eee', padding: '12px 18px', flexShrink: 0, background: '#fafafa' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '150px 150px auto 1fr auto', gap: 10, alignItems: 'flex-end' }}>
            <div>
              <label style={label}>Latitude</label>
              <input value={latText} onChange={(e) => setLatText(e.target.value)} placeholder="0.000000" style={input} />
            </div>
            <div>
              <label style={label}>Longitude</label>
              <input value={lngText} onChange={(e) => setLngText(e.target.value)} placeholder="0.000000" style={input} />
            </div>
            <button className="btn btn-sm btn-secondary" onClick={applyTyped} style={{ height: 38 }}>Go</button>

            <div style={{ minWidth: 0, paddingBottom: 2 }}>
              <label style={label}>Address</label>
              <div style={{ fontSize: 12, color: pos ? '#040404' : '#999', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={address}>
                {resolving ? 'Resolving…' : (address || (pos ? 'No address found for this point' : 'No point selected yet'))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-sm btn-secondary" onClick={onCancel} style={{ height: 38 }}>Cancel</button>
              <button
                className="btn btn-sm btn-primary"
                style={{ height: 38 }}
                disabled={!pos}
                onClick={() => pos && onConfirm({ latitude: pos.lat, longitude: pos.lng, address })}
              >
                <FiCheck size={14} /> Confirm location
              </button>
            </div>
          </div>
          {err && <div style={{ marginTop: 8, fontSize: 12, color: '#d32f2f' }}>{err}</div>}
        </div>
      </div>
    </div>
  );
}
