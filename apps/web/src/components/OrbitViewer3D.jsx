import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { createScene } from "../three/sceneSetup.js";
import { buildMarker, buildTrailLine, buildUserMarker, disposeObject } from "../three/orbitPath.js";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const TRAJECTORY_REFRESH_MS = 5 * 60_000;

// Fixed track palette, assigned by each object's position in the nearest-N
// list (stable while selection toggles — identity is also carried by the
// selector chips and the dashboard table, never color alone).
export const TRACK_COLORS = [
  0xff8a3c, 0x2ed573, 0xffc53d, 0x6eb4ff, 0xff4757, 0xd06eff, 0x5eeaf0, 0xffa9a3,
  0x9dff70, 0xffd36e, 0x8fa8ff, 0xff7ab8, 0x70e8d4, 0xffb36e,
];
const USER_COLOR = 0x6eb4ff;

/**
 * Self-contained 3D orbit viewer. Imperative three.js objects live in refs;
 * React state only drives the small status overlay.
 *
 * `tracks`: [{ id, name, color }] — full nearest-N set (fetch key).
 * `visibleIds`: ids currently shown — toggling visibility never refetches,
 * it just flips `group.visible` on the per-object THREE.Group.
 */
export default function OrbitViewer3D({ tracks, visibleIds, userPosition, hours = 3, stepSeconds = 60 }) {
  const containerRef = useRef(null);
  const sceneObjRef = useRef(null);
  const rootGroupRef = useRef(null); // parent THREE.Group of all tracks
  const groupsByIdRef = useRef(new Map()); // norad_id -> THREE.Group
  const userMarkerRef = useRef(null);
  const [status, setStatus] = useState("loading"); // "loading" | "ok" | "error" | "no-webgl"
  const [trackCount, setTrackCount] = useState(0);

  const idsKey = tracks.map((t) => t.id).join(",");
  const visibleKey = visibleIds.join(",");

  /* ---- mount once: scene + render loop ---- */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let sceneObj;
    try {
      sceneObj = createScene(container);
    } catch {
      // WebGL unavailable (old hardware, disabled, headless) — degrade to a
      // notice instead of letting the constructor error crash the whole app.
      setStatus("no-webgl");
      return;
    }
    sceneObjRef.current = sceneObj;

    let raf;
    const loop = () => {
      sceneObj.controls.update();
      sceneObj.renderer.render(sceneObj.scene, sceneObj.camera);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      if (rootGroupRef.current) {
        disposeObject(rootGroupRef.current);
        rootGroupRef.current = null;
      }
      groupsByIdRef.current.clear();
      if (userMarkerRef.current) {
        disposeObject(userMarkerRef.current);
        userMarkerRef.current = null;
      }
      sceneObj.dispose();
      sceneObjRef.current = null;
    };
  }, []);

  /* ---- fetch trajectories; rebuild per-object track groups ---- */
  useEffect(() => {
    if (!idsKey) { setStatus("ok"); setTrackCount(0); return; }
    let cancelled = false;
    const colorById = new Map(tracks.map((t) => [t.id, t.color]));

    const load = () => {
      setStatus((s) => (s === "ok" ? s : "loading"));
      fetch(`${API_BASE}/api/trajectories?norad_ids=${idsKey}&hours=${hours}&step_seconds=${stepSeconds}`)
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then((data) => {
          if (cancelled || !sceneObjRef.current) return;
          const { scene } = sceneObjRef.current;

          const root = new THREE.Group();
          const groupsById = new Map();
          data.objects.forEach((obj) => {
            if (!obj.points.length) return;
            const color = colorById.get(obj.norad_id) ?? TRACK_COLORS[0];
            const group = new THREE.Group();
            group.add(buildTrailLine(obj.points, color));
            const head = obj.points[obj.points.length - 1];
            group.add(buildMarker(head.lat, head.lon, head.alt_km, color));
            root.add(group);
            groupsById.set(obj.norad_id, group);
          });

          if (rootGroupRef.current) {
            scene.remove(rootGroupRef.current);
            disposeObject(rootGroupRef.current);
          }
          scene.add(root);
          rootGroupRef.current = root;
          groupsByIdRef.current = groupsById;

          // Apply current visibility to the fresh groups
          const visible = new Set(visibleIds);
          groupsById.forEach((group, id) => { group.visible = visible.has(id); });

          setTrackCount(groupsById.size);
          setStatus("ok");
        })
        .catch(() => { if (!cancelled) setStatus("error"); });
    };

    load();
    const id = setInterval(load, TRAJECTORY_REFRESH_MS);
    return () => { cancelled = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, hours, stepSeconds]);

  /* ---- visibility toggles (no refetch) ---- */
  useEffect(() => {
    const visible = new Set(visibleIds);
    groupsByIdRef.current.forEach((group, id) => { group.visible = visible.has(id); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleKey]);

  /* ---- user asset marker ---- */
  useEffect(() => {
    const sceneObj = sceneObjRef.current;
    if (!sceneObj || !userPosition) return;
    if (userMarkerRef.current) {
      sceneObj.scene.remove(userMarkerRef.current);
      disposeObject(userMarkerRef.current);
    }
    const marker = buildUserMarker(userPosition.lat, userPosition.lon, userPosition.alt, USER_COLOR);
    sceneObj.scene.add(marker);
    userMarkerRef.current = marker;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userPosition?.lat, userPosition?.lon, userPosition?.alt]);

  const shownCount = visibleIds.length < trackCount ? `${visibleIds.length}/${trackCount}` : `${trackCount}`;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%", cursor: "grab" }} />
      <div style={{
        position: "absolute", top: 10, left: 12, pointerEvents: "none",
        fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 10,
        color: status === "error" ? "#FF4757" : "#5E7290", letterSpacing: "0.08em",
      }}>
        {status === "loading" && "LOADING TRACKS…"}
        {status === "error" && "TRACK LINK DOWN"}
        {status === "no-webgl" && "3D VIEW UNAVAILABLE — WEBGL NOT SUPPORTED IN THIS BROWSER"}
        {status === "ok" && trackCount > 0 && `${shownCount} TRACKS · DRAG TO ROTATE · SCROLL TO ZOOM`}
        {status === "ok" && trackCount === 0 && "NO TRACKS"}
      </div>
    </div>
  );
}
