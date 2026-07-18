import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Radar, Satellite, AlertTriangle, Crosshair, Orbit, Rocket,
  Wifi, WifiOff, Loader2, Volume2, VolumeX, Clock, MapPin,
  ZoomIn, ZoomOut, Activity,
} from "lucide-react";

/* ==================================================================
   SAKLE — Space Analytics & Kinetic Location Engine
   Live console over the conjunction FastAPI backend. All orbital
   state (SGP4 propagation, ranking, risk scoring) is computed
   server-side; this client only renders and polls.
================================================================== */

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const PROXIMITY_POLL_MS = 10_000;
const CATALOG_POLL_MS = 60_000;
const PROXIMITY_LIMIT = 200;
const SCOPE_COUNT = 14;

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (deg) => COMPASS[Math.round(deg / 22.5) % 16];

/* ---- ISRO theme tokens (validated ≥3:1 on the dark surface) ---- */
const T = {
  page: "#050A13",
  surface: "#0B1424",
  surface2: "#0F1B30",
  border: "#1B2A44",
  grid: "#16233B",
  ink: "#EDF2F9",
  ink2: "#9FB0C9",
  muted: "#5E7290",
  saffron: "#FF8A3C",
  saffronDeep: "#FF671F",
  chakra: "#6EB4FF",
  good: "#2ED573",
  warning: "#FFC53D",
  critical: "#FF4757",
};

const LEVEL_META = {
  red: { color: T.critical, glow: "rgba(255,71,87,0.30)", label: "CRITICAL" },
  yellow: { color: T.warning, glow: "rgba(255,197,61,0.24)", label: "CAUTION" },
  green: { color: T.good, glow: "rgba(46,213,115,0.20)", label: "NOMINAL" },
};

const FONT_SANS = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const FONT_MONO = 'ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace';

/* ==================================================================
   COMPONENT
================================================================== */
export default function SakleDashboard() {
  const [lat, setLat] = useState(13.72);
  const [lon, setLon] = useState(80.23);
  const [alt, setAlt] = useState(780);

  const [proximity, setProximity] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [linkError, setLinkError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);

  const [now, setNow] = useState(() => new Date());
  const [geo, setGeo] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [muted, setMuted] = useState(false);
  const audioRef = useRef(null);

  /* ---------------- clock ---------------- */
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  /* ---------------- geolocation ---------------- */
  useEffect(() => {
    if (!navigator.geolocation) { setGeo("unavailable"); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => setGeo({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => setGeo("unavailable"),
      { timeout: 8000 },
    );
  }, []);

  /* ---------------- background audio ----------------
     Starts at launch. Browsers may veto audible autoplay until the
     origin has engagement — so retry for a while and also unlock on
     the first interaction, whichever comes first. */
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    a.volume = 0.3;
    let started = false;
    const tryPlay = () => {
      if (started) return;
      a.play().then(() => { started = true; }).catch(() => {});
    };
    tryPlay();
    const retry = setInterval(() => { started ? clearInterval(retry) : tryPlay(); }, 1000);
    const unlock = () => {
      tryPlay();
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    const onVisible = () => { if (!document.hidden) tryPlay(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(retry);
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = muted;
  }, [muted]);

  /* ---------------- live polling ---------------- */
  const posRef = useRef({ lat, lon, alt });
  posRef.current = { lat, lon, alt };

  const fetchProximity = useCallback(() => {
    const p = posRef.current;
    setSyncing(true);
    fetch(`${API_BASE}/api/proximity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: p.lat, lon: p.lon, altitude_km: p.alt, limit: PROXIMITY_LIMIT }),
    })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data) => { setProximity(data); setLinkError(null); setLastSync(Date.now()); })
      .catch((err) => setLinkError(err.message || "Link failure"))
      .finally(() => setSyncing(false));
  }, []);

  const fetchCatalog = useCallback(() => {
    fetch(`${API_BASE}/api/catalog`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data) => { setCatalog(data); setLinkError(null); })
      .catch((err) => setLinkError((prev) => prev || err.message || "Link failure"));
  }, []);

  // Debounced re-fetch on position change
  useEffect(() => {
    const h = setTimeout(fetchProximity, 350);
    return () => clearTimeout(h);
  }, [lat, lon, alt, fetchProximity]);

  // Regular polling intervals
  useEffect(() => {
    const id = setInterval(fetchProximity, PROXIMITY_POLL_MS);
    return () => clearInterval(id);
  }, [fetchProximity]);

  useEffect(() => {
    fetchCatalog();
    const id = setInterval(fetchCatalog, CATALOG_POLL_MS);
    return () => clearInterval(id);
  }, [fetchCatalog]);

  /* ---------------- derived data ---------------- */
  const ranked = useMemo(() => {
    if (!proximity) return [];
    return proximity.objects.map((o) => ({
      id: o.norad_id,
      name: o.name,
      kind: o.kind,
      altitude_km: o.altitude_km,
      lat: o.lat,
      lon: o.lon,
      distanceKm: o.distance_km,
      bearingDeg: o.bearing_deg,
      altDiffKm: o.alt_diff_km,
      riskScore: o.risk_score,
      riskLevel: o.risk_level,
    }));
  }, [proximity]);

  const nearest = ranked[0];
  const hasData = Boolean(nearest);
  const meta = hasData ? LEVEL_META[nearest.riskLevel] : null;

  const riskCounts = useMemo(() => {
    const c = { red: 0, yellow: 0, green: 0 };
    ranked.forEach((o) => { c[o.riskLevel] += 1; });
    return c;
  }, [ranked]);

  const catalogStats = useMemo(() => {
    const objs = catalog?.objects ?? [];
    if (!objs.length) return null;
    // Restrict stats to plausible LEO altitudes — a handful of decayed or
    // badly-conditioned TLEs propagate to absurd radii and would wreck the mean.
    let sum = 0, min = Infinity, max = -Infinity, n = 0;
    objs.forEach((o) => {
      const a = o.altitude_km;
      if (a < 100 || a > 3000) return;
      sum += a; n += 1;
      if (a < min) min = a;
      if (a > max) max = a;
    });
    if (!n) return { count: objs.length, meanAlt: null, minAlt: null, maxAlt: null };
    return { count: objs.length, meanAlt: sum / n, minAlt: min, maxAlt: max };
  }, [catalog]);

  // Altitude-band congestion — 50km bins, 350–1250km
  const bands = useMemo(() => {
    const binSize = 50, minAlt = 350, maxAlt = 1250;
    const nBins = Math.round((maxAlt - minAlt) / binSize);
    const counts = Array.from({ length: nBins }, (_, i) => ({
      lo: minAlt + i * binSize, hi: minAlt + (i + 1) * binSize, count: 0,
    }));
    (catalog?.objects ?? []).forEach((d) => {
      const idx = Math.floor((d.altitude_km - minAlt) / binSize);
      if (idx >= 0 && idx < nBins) counts[idx].count += 1;
    });
    return counts;
  }, [catalog]);
  const maxBandCount = Math.max(...bands.map((b) => b.count), 1);
  const userBandIdx = Math.floor((alt - 350) / 50);

  // Radar scope — nearest N, with zoom
  const scopeObjects = ranked.slice(0, SCOPE_COUNT);
  const baseRange = Math.max(...scopeObjects.map((o) => o.distanceKm), 1);
  const displayRange = baseRange / zoom;
  const visibleScope = scopeObjects.filter((o) => o.distanceKm <= displayRange);

  const epochLabel = proximity?.epoch || catalog?.epoch || "—";
  const syncAgo = lastSync ? Math.max(0, Math.round((now.getTime() - lastSync) / 1000)) : null;

  const fmtTime = (d, tz) =>
    d.toLocaleTimeString("en-IN", { hour12: false, timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const fmtDate = (d) =>
    d.toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Kolkata" }).toUpperCase();

  const geoLabel =
    geo && geo !== "unavailable"
      ? `${Math.abs(geo.lat).toFixed(4)}°${geo.lat >= 0 ? "N" : "S"}  ${Math.abs(geo.lon).toFixed(4)}°${geo.lon >= 0 ? "E" : "W"}`
      : geo === "unavailable" ? "UNAVAILABLE" : "ACQUIRING…";

  return (
    <div style={styles.page}>
      <audio ref={audioRef} src="/audio/music.mp3" loop autoPlay preload="auto" />

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulseDot { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
        .sk-spin { animation: spin 1s linear infinite; }
        .sk-fade { animation: fadeUp 0.45s ease both; }
        .sk-pulse { animation: pulseDot 2s ease-in-out infinite; }
        .sk-slider { -webkit-appearance: none; appearance: none; height: 3px; border-radius: 2px; background: ${T.grid}; outline: none; }
        .sk-slider::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 14px; height: 14px; border-radius: 50%; background: ${T.saffron}; box-shadow: 0 0 8px rgba(255,138,60,0.55); cursor: pointer; transition: transform 0.15s ease; }
        .sk-slider::-webkit-slider-thumb:hover { transform: scale(1.2); }
        .sk-slider::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: ${T.saffron}; box-shadow: 0 0 8px rgba(255,138,60,0.55); cursor: pointer; border: none; }
        .sk-row { transition: background 0.2s ease; }
        .sk-row:hover { background: ${T.surface2} !important; }
        .sk-iconbtn { transition: all 0.2s ease; }
        .sk-iconbtn:hover { border-color: ${T.saffron} !important; color: ${T.ink} !important; }
        .sk-panel { transition: border-color 0.4s ease, box-shadow 0.4s ease; }
        .sk-blip { transition: transform 0.9s cubic-bezier(0.25, 0.8, 0.35, 1); }
      `}</style>

      {/* ================= HEADER ================= */}
      <header style={styles.header} className="sk-fade">
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={styles.emblem}>
            <Rocket size={22} color="#FFF" strokeWidth={1.75} />
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <div style={styles.h1}>SAKLE</div>
              <div style={styles.h1Hi}>साकले</div>
            </div>
            <div style={styles.subtitle}>SPACE ANALYTICS &amp; KINETIC LOCATION ENGINE</div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* live time + location */}
          <div style={styles.timeCard}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Clock size={13} color={T.saffron} />
              <span style={{ ...styles.mono, fontSize: 20, fontWeight: 600, color: T.ink, letterSpacing: "0.04em" }}>
                {fmtTime(now, "Asia/Kolkata")}
              </span>
              <span style={{ fontSize: 10, color: T.saffron, fontWeight: 700, letterSpacing: "0.08em" }}>IST</span>
            </div>
            <div style={{ ...styles.mono, fontSize: 10, color: T.ink2, marginTop: 3 }}>
              {fmtDate(now)} · {fmtTime(now, "UTC")} UTC
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
              <MapPin size={10} color={T.muted} />
              <span style={{ ...styles.mono, fontSize: 10, color: T.muted, letterSpacing: "0.03em" }}>{geoLabel}</span>
            </div>
          </div>

          <button
            className="sk-iconbtn"
            onClick={() => setMuted((m) => !m)}
            title={muted ? "Unmute ambience" : "Mute ambience"}
            style={styles.iconBtn}
          >
            {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
          </button>
        </div>
      </header>

      {/* tricolor rule */}
      <div style={styles.tricolor} />

      {/* ================= STATUS STRIP ================= */}
      <div style={styles.statusStrip} className="sk-fade">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {linkError ? (
            <>
              <WifiOff size={13} color={T.critical} />
              <span style={{ fontSize: 10.5, color: T.critical, letterSpacing: "0.08em", fontWeight: 600 }}>
                TELEMETRY LINK DOWN — RETRYING
              </span>
            </>
          ) : hasData ? (
            <>
              <div className="sk-pulse" style={{ width: 7, height: 7, borderRadius: "50%", background: T.good, boxShadow: `0 0 8px ${T.good}` }} />
              <span style={{ fontSize: 10.5, color: T.ink2, letterSpacing: "0.08em", fontWeight: 600 }}>TELEMETRY LINK ACTIVE</span>
              {syncing && <Loader2 size={11} color={T.muted} className="sk-spin" />}
            </>
          ) : (
            <>
              <Loader2 size={13} color={T.saffron} className="sk-spin" />
              <span style={{ fontSize: 10.5, color: T.ink2, letterSpacing: "0.08em", fontWeight: 600 }}>ACQUIRING TELEMETRY…</span>
            </>
          )}
        </div>
        <div style={{ ...styles.mono, fontSize: 10, color: T.muted }}>
          EPOCH {epochLabel !== "—" ? epochLabel.replace("T", " · ").slice(0, 25) : "—"}
        </div>
      </div>

      {/* ================= MAIN GRID ================= */}
      {hasData ? (
        <>
          <div style={styles.grid} className="sk-fade">
            {/* -------- LEFT COLUMN: position + status -------- */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* -------- POSITION -------- */}
              <section style={styles.panel} className="sk-panel">
                <div style={styles.panelTitle}><Crosshair size={13} color={T.saffron} /> ASSET POSITION</div>
                <SliderRow label="LATITUDE" value={lat} min={-90} max={90} step={0.01} unit="°" onChange={setLat} />
                <SliderRow label="LONGITUDE" value={lon} min={-180} max={180} step={0.01} unit="°" onChange={setLon} />
                <SliderRow label="ALTITUDE" value={alt} min={350} max={1250} step={0.5} unit=" km" onChange={setAlt} />

                <div style={{ marginTop: 16, padding: "10px 12px", background: T.surface2, borderRadius: 6, border: `1px solid ${T.border}` }}>
                  <div style={styles.eyebrow}>GROUND TRACK</div>
                  <div style={{ ...styles.mono, fontSize: 12, color: T.ink2, marginTop: 5, lineHeight: 1.7 }}>
                    {Math.abs(lat).toFixed(2)}°{lat >= 0 ? "N" : "S"} · {Math.abs(lon).toFixed(2)}°{lon >= 0 ? "E" : "W"}
                    <br />
                    ORBIT SHELL {alt.toFixed(1)} km
                  </div>
                </div>
              </section>

              {/* -------- STATUS -------- */}
              <section style={{ ...styles.panel, flex: 1, borderColor: meta.color, boxShadow: `0 0 26px ${meta.glow}` }} className="sk-panel">
              <div style={styles.panelTitle}><AlertTriangle size={13} color={meta.color} /> CONJUNCTION STATUS</div>

              <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "12px 0 14px" }}>
                <div style={{ width: 13, height: 13, borderRadius: "50%", background: meta.color, boxShadow: `0 0 14px ${meta.color}`, transition: "background 0.5s ease, box-shadow 0.5s ease" }} />
                <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "0.05em", color: meta.color, transition: "color 0.5s ease" }}>
                  {meta.label}
                </div>
              </div>

              <StatRow label="NEAREST OBJECT" value={nearest.name} />
              <StatRow label="NORAD ID" value={String(nearest.id)} />
              <StatRow label="RANGE" value={`${nearest.distanceKm.toFixed(2)} km`} accent />
              <StatRow label="BEARING" value={`${nearest.bearingDeg.toFixed(0)}° ${compass(nearest.bearingDeg)}`} />
              <StatRow label="ALTITUDE Δ" value={`${nearest.altDiffKm >= 0 ? "+" : ""}${nearest.altDiffKm.toFixed(1)} km`} />

              <div style={{ marginTop: 14 }}>
                <div style={styles.eyebrow}>RISK INDEX</div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                  <div style={{ flex: 1, height: 6, background: T.grid, borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ width: `${nearest.riskScore * 100}%`, height: "100%", background: meta.color, borderRadius: 3, transition: "width 0.7s ease, background 0.5s ease" }} />
                  </div>
                  <div style={{ ...styles.mono, color: meta.color, fontSize: 13, minWidth: 42, textAlign: "right", transition: "color 0.5s ease" }}>
                    {(nearest.riskScore * 100).toFixed(0)}%
                  </div>
                </div>
              </div>
            </section>
            </div>

            {/* -------- RADAR SCOPE — big side card -------- */}
            <section style={{ ...styles.panel, display: "flex", flexDirection: "column" }} className="sk-panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={styles.panelTitle}><Orbit size={13} color={T.saffron} /> PROXIMITY SCOPE</div>
                <div style={{ ...styles.mono, fontSize: 12, color: T.saffron, fontWeight: 600 }}>
                  ⌀ {displayRange >= 100 ? Math.round(displayRange).toLocaleString("en-IN") : displayRange.toFixed(1)} km
                </div>
              </div>

              {/* zoom control */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                <button className="sk-iconbtn" style={styles.zoomBtn} onClick={() => setZoom((z) => Math.max(1, +(z - 0.5).toFixed(1)))} title="Zoom out">
                  <ZoomOut size={12} />
                </button>
                <input
                  className="sk-slider" type="range" min={1} max={10} step={0.5} value={zoom}
                  onChange={(e) => setZoom(parseFloat(e.target.value))}
                  style={{ flex: 1 }} title={`Zoom ${zoom}×`}
                />
                <button className="sk-iconbtn" style={styles.zoomBtn} onClick={() => setZoom((z) => Math.min(10, +(z + 0.5).toFixed(1)))} title="Zoom in">
                  <ZoomIn size={12} />
                </button>
                <span style={{ ...styles.mono, fontSize: 10, color: T.muted, minWidth: 30, textAlign: "right" }}>{zoom.toFixed(1)}×</span>
              </div>

              <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <RadarScope objects={visibleScope} maxRange={displayRange} radiusPx={185} />
              </div>

              <div style={styles.scopeLegend}>
                <LegendDot color={T.critical} label="CRITICAL" />
                <LegendDot color={T.warning} label="CAUTION" />
                <LegendDot color={T.good} label="NOMINAL" />
                {visibleScope.length < scopeObjects.length && (
                  <span style={{ ...styles.mono, fontSize: 9.5, color: T.muted }}>
                    {visibleScope.length}/{scopeObjects.length} IN RANGE
                  </span>
                )}
              </div>
            </section>
          </div>

          {/* ================= ANALYTICS TILES ================= */}
          <div style={styles.tileRow} className="sk-fade">
            <StatTile icon={Satellite} label="Objects tracked" value={catalogStats ? catalogStats.count.toLocaleString("en-IN") : "—"} sub="resident space objects" />
            <StatTile icon={Activity} label="Screened" value={proximity ? proximity.total_objects_considered.toLocaleString("en-IN") : "—"} sub="per proximity pass" />
            <StatTile icon={AlertTriangle} label="Critical contacts" value={String(riskCounts.red)} color={T.critical} sub={`< ${proximity?.thresholds_km?.red ?? 5} km`} />
            <StatTile icon={AlertTriangle} label="Caution contacts" value={String(riskCounts.yellow)} color={T.warning} sub={`< ${proximity?.thresholds_km?.yellow ?? 25} km`} />
            <StatTile icon={Radar} label="Nearest range" value={`${nearest.distanceKm.toFixed(1)}`} sub="km miss distance" />
            <StatTile icon={Orbit} label="Mean altitude" value={catalogStats?.meanAlt ? `${Math.round(catalogStats.meanAlt).toLocaleString("en-IN")}` : "—"} sub={catalogStats?.meanAlt ? `km · span ${Math.round(catalogStats.minAlt)}–${Math.round(catalogStats.maxAlt)}` : "km"} />
            <StatTile icon={Clock} label="Last sync" value={syncAgo === null ? "—" : `${syncAgo}s`} sub={`refresh ${PROXIMITY_POLL_MS / 1000}s`} />
          </div>

          {/* ================= ALTITUDE DENSITY ================= */}
          <section style={{ ...styles.panel, marginTop: 14 }} className="sk-panel sk-fade">
            <div style={styles.panelTitle}><Satellite size={13} color={T.saffron} /> OBJECT DENSITY BY ALTITUDE BAND</div>
            <AltitudeBandChart bands={bands} maxCount={maxBandCount} userBandIdx={userBandIdx} />
          </section>

          {/* ================= NEAREST OBJECTS ================= */}
          <section style={{ ...styles.panel, marginTop: 14 }} className="sk-panel sk-fade">
            <div style={styles.panelTitle}><Radar size={13} color={T.saffron} /> NEAREST OBJECTS — RANKED</div>
            <div style={{ marginTop: 6 }}>
              <div style={styles.tableHeader}>
                <span style={{ flex: 2.1 }}>OBJECT</span>
                <span style={{ flex: 0.9 }}>NORAD</span>
                <span style={{ flex: 1, textAlign: "right" }}>ALT (km)</span>
                <span style={{ flex: 1, textAlign: "right" }}>RANGE (km)</span>
                <span style={{ flex: 1, textAlign: "right" }}>BEARING</span>
                <span style={{ flex: 1, textAlign: "right" }}>Δ ALT (km)</span>
                <span style={{ flex: 1.1, textAlign: "center" }}>STATUS</span>
              </div>
              {ranked.slice(0, 12).map((o) => {
                const lm = LEVEL_META[o.riskLevel];
                return (
                  <div key={o.id} className="sk-row" style={styles.tableRow}>
                    <span style={{ flex: 2.1, color: T.ink }}>{o.name}</span>
                    <span style={{ flex: 0.9, ...styles.mono, color: T.muted, fontSize: 11 }}>{o.id}</span>
                    <span style={{ flex: 1, textAlign: "right", ...styles.mono }}>{o.altitude_km.toFixed(1)}</span>
                    <span style={{ flex: 1, textAlign: "right", ...styles.mono, color: T.ink }}>{o.distanceKm.toFixed(1)}</span>
                    <span style={{ flex: 1, textAlign: "right", ...styles.mono, fontSize: 11.5 }}>{o.bearingDeg.toFixed(0)}° {compass(o.bearingDeg)}</span>
                    <span style={{ flex: 1, textAlign: "right", ...styles.mono, fontSize: 11.5 }}>{o.altDiffKm >= 0 ? "+" : ""}{o.altDiffKm.toFixed(1)}</span>
                    <span style={{ flex: 1.1, display: "flex", justifyContent: "center", alignItems: "center", gap: 6 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: lm.color, boxShadow: `0 0 6px ${lm.color}` }} />
                      <span style={{ fontSize: 9.5, color: T.ink2, letterSpacing: "0.06em" }}>{lm.label}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      ) : (
        /* ================= AWAITING LINK ================= */
        <div style={{ ...styles.panel, minHeight: 320, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }} className="sk-fade">
          {linkError ? (
            <>
              <WifiOff size={26} color={T.critical} />
              <div style={{ color: T.ink, fontSize: 14, fontWeight: 600, letterSpacing: "0.04em" }}>TELEMETRY LINK DOWN</div>
              <div style={{ color: T.muted, fontSize: 11.5 }}>Reconnecting to ground station automatically…</div>
            </>
          ) : (
            <>
              <Loader2 size={26} color={T.saffron} className="sk-spin" />
              <div style={{ color: T.ink2, fontSize: 13, letterSpacing: "0.04em" }}>ESTABLISHING TELEMETRY LINK…</div>
            </>
          )}
        </div>
      )}

      <footer style={styles.footer}>
        SAKLE · SPACE ANALYTICS &amp; KINETIC LOCATION ENGINE
      </footer>
    </div>
  );
}

/* ==================================================================
   SUBCOMPONENTS
================================================================== */
function SliderRow({ label, value, min, max, step, unit, onChange }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={styles.eyebrow}>{label}</span>
        <span style={{ ...styles.mono, color: T.saffron, fontSize: 12.5 }}>{value.toFixed(2)}{unit}</span>
      </div>
      <input
        className="sk-slider" type="range"
        min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: "100%" }}
      />
    </div>
  );
}

function StatRow({ label, value, accent }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "6px 0", borderBottom: `1px solid ${T.grid}` }}>
      <span style={{ fontSize: 10.5, color: T.muted, letterSpacing: "0.07em" }}>{label}</span>
      <span style={{ ...styles.mono, fontSize: accent ? 15 : 12.5, color: accent ? T.ink : T.ink2, fontWeight: accent ? 600 : 400 }}>{value}</span>
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 7, height: 7, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}` }} />
      <span style={{ fontSize: 10, color: T.muted, letterSpacing: "0.05em" }}>{label}</span>
    </div>
  );
}

function StatTile({ icon: Icon, label, value, sub, color }) {
  return (
    <div style={styles.tile} className="sk-panel">
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Icon size={12} color={color || T.saffron} />
        <span style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: "0.08em", color: T.muted, textTransform: "uppercase" }}>{label}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 650, color: color || T.ink, marginTop: 6, lineHeight: 1.1, transition: "color 0.4s ease" }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: T.muted, marginTop: 4, letterSpacing: "0.03em" }}>{sub}</div>}
    </div>
  );
}

/* -------- radar scope with hover tooltips + synced sweep -------- */
const SWEEP_PERIOD_MS = 10_000; // one revolution every 10s
const AFTERGLOW_DEG = 70; // how far past a blip the highlight fades

function RadarScope({ objects, maxRange, radiusPx }) {
  const [hover, setHover] = useState(null); // { o, x, y }
  const [sweepDeg, setSweepDeg] = useState(0);
  const size = radiusPx * 2 + 14;
  const cx = size / 2, cy = size / 2;
  const rings = [0.25, 0.5, 0.75, 1.0];

  // JS-driven sweep (instead of a CSS animation) so each blip can be
  // highlighted at the exact moment the beam crosses its bearing.
  // Runs regardless of prefers-reduced-motion: the sweep IS the display's
  // core function, not decoration.
  useEffect(() => {
    let raf;
    const loop = (t) => {
      setSweepDeg(((t % SWEEP_PERIOD_MS) / SWEEP_PERIOD_MS) * 360);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div style={{ position: "relative", display: "flex", justifyContent: "center", padding: 0 }}>
      {/* rotating afterglow trail — conic gradient fading to transparent
          behind the beam, layered under the SVG rings/blips */}
      <div
        style={{
          position: "absolute",
          left: `calc(50% - ${radiusPx}px)`,
          top: cy - radiusPx,
          width: radiusPx * 2,
          height: radiusPx * 2,
          borderRadius: "50%",
          pointerEvents: "none",
          background: `conic-gradient(from ${sweepDeg}deg, transparent 0deg, transparent 250deg, rgba(46,213,115,0.02) 265deg, rgba(46,213,115,0.09) 305deg, rgba(46,213,115,0.22) 345deg, rgba(46,213,115,0.38) 360deg)`,
        }}
      />
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ position: "relative" }}>
        {rings.map((f) => (
          <circle key={f} cx={cx} cy={cy} r={radiusPx * f} fill="none" stroke={T.grid} strokeWidth="1" />
        ))}
        <line x1={cx} y1={cy - radiusPx} x2={cx} y2={cy + radiusPx} stroke={T.grid} strokeWidth="1" opacity="0.6" />
        <line x1={cx - radiusPx} y1={cy} x2={cx + radiusPx} y2={cy} stroke={T.grid} strokeWidth="1" opacity="0.6" />

        {/* sweep beam — one revolution every 10s, angle driven by rAF;
            the gradient trail behind it is the conic-gradient layer below */}
        <g style={{ transform: `rotate(${sweepDeg}deg)`, transformOrigin: `${cx}px ${cy}px` }}>
          <line x1={cx} y1={cy} x2={cx} y2={cy - radiusPx} stroke={T.good} strokeWidth="1.8" opacity="0.85" />
          <circle cx={cx} cy={cy - radiusPx} r="2.5" fill={T.good} opacity="0.9" />
        </g>

        {/* range labels */}
        {rings.map((f) => (
          <text key={f} x={cx + 5} y={cy - radiusPx * f + 12} fill={T.muted} fontSize="9.5" fontFamily={FONT_MONO}>
            {maxRange * f >= 100 ? Math.round(maxRange * f).toLocaleString("en-IN") : (maxRange * f).toFixed(1)}km
          </text>
        ))}

        {/* blips — flare when the sweep beam crosses their bearing */}
        {objects.map((o) => {
          const angleRad = (o.bearingDeg * Math.PI) / 180;
          const r = (Math.min(o.distanceKm, maxRange) / maxRange) * radiusPx;
          const x = cx + r * Math.sin(angleRad);
          const y = cy - r * Math.cos(angleRad);
          const color = LEVEL_META[o.riskLevel].color;
          // Degrees since the beam last passed this blip → afterglow 1 → 0
          const angBehind = (sweepDeg - o.bearingDeg + 360) % 360;
          const glow = Math.max(0, 1 - angBehind / AFTERGLOW_DEG);
          const isHover = hover?.o.id === o.id;
          return (
            <g key={o.id} className="sk-blip" style={{ transform: `translate(${x}px, ${y}px)` }}>
              <circle r="13" fill="transparent" style={{ cursor: "pointer" }}
                onMouseEnter={() => setHover({ o, x, y })}
                onMouseLeave={() => setHover(null)}
              />
              {/* expanding ping ring emitted as the beam passes */}
              {glow > 0 && (
                <circle r={7 + (1 - glow) * 15} fill="none" stroke={color} strokeWidth="1.4" opacity={glow * 0.7} pointerEvents="none" />
              )}
              <circle r={5.5 + glow * 2} fill={color} opacity={0.55 + glow * 0.45} pointerEvents="none"
                style={glow > 0.6 ? { filter: `drop-shadow(0 0 5px ${color})` } : undefined} />
              <circle r="9" fill="none" stroke={color} strokeWidth="1" opacity={isHover ? 0.9 : 0.3} pointerEvents="none" style={{ transition: "opacity 0.2s ease" }} />
            </g>
          );
        })}

        {/* asset marker (center) */}
        <circle cx={cx} cy={cy} r="4.5" fill={T.chakra} />
        <circle cx={cx} cy={cy} r="9" fill="none" stroke={T.chakra} strokeWidth="1.2" opacity="0.6" />
      </svg>

      {/* hover detail card */}
      {hover && (
        <div
          style={{
            position: "absolute",
            left: `calc(50% - ${size / 2}px + ${hover.x}px)`,
            top: hover.y + 14,
            transform: hover.y > size * 0.6 ? "translate(-50%, -130%)" : "translate(-50%, 10px)",
            background: "rgba(11,20,36,0.96)",
            border: `1px solid ${LEVEL_META[hover.o.riskLevel].color}`,
            borderRadius: 6,
            padding: "8px 10px",
            pointerEvents: "none",
            zIndex: 10,
            minWidth: 168,
            boxShadow: `0 4px 18px rgba(0,0,0,0.5), 0 0 12px ${LEVEL_META[hover.o.riskLevel].glow}`,
            animation: "fadeUp 0.18s ease both",
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 700, color: T.ink, letterSpacing: "0.04em", marginBottom: 5 }}>
            {hover.o.name}
          </div>
          <TipRow k="NORAD" v={String(hover.o.id)} />
          <TipRow k="RANGE" v={`${hover.o.distanceKm.toFixed(2)} km`} />
          <TipRow k="BEARING" v={`${hover.o.bearingDeg.toFixed(0)}° ${compass(hover.o.bearingDeg)}`} />
          <TipRow k="ALT" v={`${hover.o.altitude_km.toFixed(1)} km (Δ ${hover.o.altDiffKm >= 0 ? "+" : ""}${hover.o.altDiffKm.toFixed(1)})`} />
          <TipRow k="STATUS" v={LEVEL_META[hover.o.riskLevel].label} color={LEVEL_META[hover.o.riskLevel].color} />
        </div>
      )}
    </div>
  );
}

function TipRow({ k, v, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "1.5px 0" }}>
      <span style={{ fontSize: 9, color: T.muted, letterSpacing: "0.07em" }}>{k}</span>
      <span style={{ ...styles.mono, fontSize: 10, color: color || T.ink2 }}>{v}</span>
    </div>
  );
}

/* -------- altitude density (single-hue saffron) -------- */
function AltitudeBandChart({ bands, maxCount, userBandIdx }) {
  const [hover, setHover] = useState(null);
  const chartH = 92;
  return (
    <div style={{ marginTop: 28, position: "relative" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: chartH }}>
        {bands.map((b, i) => {
          const h = Math.max((b.count / maxCount) * chartH, b.count > 0 ? 3 : 0);
          const isUser = i === userBandIdx;
          return (
            <div
              key={i}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: chartH, position: "relative", cursor: "default" }}
            >
              {isUser && (
                <div style={{ position: "absolute", top: -14, fontSize: 8, color: T.chakra, ...styles.mono }}>ASSET</div>
              )}
              {hover === i && (
                <div style={{
                  position: "absolute", top: -34, background: "rgba(11,20,36,0.96)", border: `1px solid ${T.border}`,
                  borderRadius: 5, padding: "3px 8px", whiteSpace: "nowrap", zIndex: 5, pointerEvents: "none",
                  ...styles.mono, fontSize: 10, color: T.ink2,
                }}>
                  {b.lo}–{b.hi} km · <span style={{ color: T.ink, fontWeight: 600 }}>{b.count.toLocaleString("en-IN")}</span>
                </div>
              )}
              <div
                style={{
                  width: "100%", maxWidth: 14, height: `${h}px`,
                  background: b.count > 0 ? (hover === i ? T.saffronDeep : T.saffron) : T.surface2,
                  opacity: b.count > 0 ? 0.9 : 1,
                  borderRadius: "3px 3px 0 0",
                  outline: isUser ? `1.5px solid ${T.chakra}` : "none",
                  transition: "height 0.6s ease, background 0.2s ease",
                }}
              />
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 9, color: T.muted, ...styles.mono }}>
        <span>350 km</span><span>700 km</span><span>1050 km</span><span>1250 km</span>
      </div>
    </div>
  );
}

/* ==================================================================
   STYLE TOKENS
================================================================== */
const styles = {
  page: {
    minHeight: "100vh",
    background: `radial-gradient(1200px 600px at 70% -10%, #0B1A33 0%, ${T.page} 55%)`,
    color: T.ink2,
    fontFamily: FONT_SANS,
    padding: "22px clamp(16px, 4vw, 40px) 30px",
    maxWidth: 1180,
    margin: "0 auto",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 16,
    flexWrap: "wrap",
    paddingBottom: 14,
  },
  emblem: {
    width: 44, height: 44, borderRadius: "50%",
    background: `linear-gradient(135deg, ${T.saffronDeep}, #C2410C)`,
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 0 22px rgba(255,103,31,0.4)",
  },
  h1: { fontSize: 26, fontWeight: 800, letterSpacing: "0.18em", color: T.ink, lineHeight: 1 },
  h1Hi: { fontSize: 22, fontWeight: 700, color: T.saffron, lineHeight: 1 },
  subtitle: { fontSize: 10, fontWeight: 600, letterSpacing: "0.14em", color: T.saffron, marginTop: 5 },
  tricolor: {
    height: 3, borderRadius: 2, marginBottom: 12,
    background: "linear-gradient(90deg, #FF9933 0%, #FF9933 32%, #F4F4F0 44%, #F4F4F0 56%, #138808 68%, #138808 100%)",
    opacity: 0.85,
  },
  timeCard: {
    background: T.surface,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "10px 14px",
    textAlign: "right",
    minWidth: 190,
  },
  iconBtn: {
    background: T.surface,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    width: 38, height: 38,
    display: "flex", alignItems: "center", justifyContent: "center",
    color: T.ink2, cursor: "pointer",
  },
  statusStrip: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: T.surface, border: `1px solid ${T.border}`, borderRadius: 8,
    padding: "8px 14px", marginBottom: 14, flexWrap: "wrap", gap: 6,
  },
  eyebrow: { fontSize: 10, fontWeight: 600, letterSpacing: "0.1em", color: T.muted, textTransform: "uppercase" },
  mono: { fontFamily: FONT_MONO, fontVariantNumeric: "tabular-nums" },
  grid: { display: "grid", gridTemplateColumns: "minmax(300px, 1fr) 1.5fr", gap: 14, alignItems: "stretch" },
  panel: {
    background: T.surface,
    border: `1px solid ${T.border}`,
    borderRadius: 10,
    padding: 16,
  },
  panelTitle: {
    display: "flex", alignItems: "center", gap: 6,
    fontSize: 11, fontWeight: 700, letterSpacing: "0.09em", color: T.ink2,
  },
  tileRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
    gap: 10, marginTop: 14,
  },
  tile: {
    background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10,
    padding: "12px 14px",
  },
  scopeLegend: { display: "flex", justifyContent: "center", alignItems: "center", gap: 14, marginTop: 2, flexWrap: "wrap" },
  tableHeader: {
    display: "flex", padding: "6px 8px", fontSize: 9.5, letterSpacing: "0.06em",
    color: T.muted, borderBottom: `1px solid ${T.grid}`,
  },
  tableRow: {
    display: "flex", padding: "8px 8px", fontSize: 12,
    borderBottom: `1px solid ${T.grid}`, alignItems: "center", borderRadius: 4,
    color: T.ink2,
  },
  footer: {
    marginTop: 20, fontSize: 9, color: T.muted, textAlign: "center", letterSpacing: "0.12em",
  },
};
