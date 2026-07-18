import * as THREE from "three";
import { EARTH_RADIUS_KM, KM_TO_UNITS } from "./sceneSetup.js";

/*
 * Trajectory points arrive as Earth-fixed geodetic {lat, lon, alt_km}
 * (converted server-side via teme_to_geodetic). We plot them against a
 * static Earth mesh — i.e. the ground track extruded to altitude — and
 * deliberately do NOT spin the Earth with GMST. That keeps the view simple
 * and the paths correct relative to the rendered Earth.
 */

export function latLonAltToVector3(lat, lon, altKm, target = new THREE.Vector3()) {
  const r = (EARTH_RADIUS_KM + altKm) * KM_TO_UNITS;
  const latR = THREE.MathUtils.degToRad(lat);
  const lonR = THREE.MathUtils.degToRad(lon);
  const x = r * Math.cos(latR) * Math.cos(lonR);
  const y = r * Math.sin(latR);
  const z = -r * Math.cos(latR) * Math.sin(lonR); // -z so east longitude runs the right way in three's RH frame
  return target.set(x, y, z);
}

/**
 * Trail line: only the most recent `trailFraction` of the trajectory is
 * drawn (so multi-orbit windows don't overwrite themselves into a tangle),
 * and it fades toward the tail via per-vertex colors darkening into the
 * space background — head is at the object's current position.
 */
export function buildTrailLine(points, color, trailFraction = 1 / 18) {
  const n = Math.max(2, Math.round(points.length * trailFraction));
  const tail = points.slice(-n);

  const positions = tail.map((p) => latLonAltToVector3(p.lat, p.lon, p.alt_km));
  const geometry = new THREE.BufferGeometry().setFromPoints(positions);

  const base = new THREE.Color(color);
  const colors = new Float32Array(tail.length * 3);
  for (let i = 0; i < tail.length; i++) {
    const f = tail.length > 1 ? i / (tail.length - 1) : 1; // 0 = tail, 1 = head
    const brightness = 0.04 + 0.96 * f * f; // quadratic fade into the dark
    colors[i * 3] = base.r * brightness;
    colors[i * 3 + 1] = base.g * brightness;
    colors[i * 3 + 2] = base.b * brightness;
  }
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  const material = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95 });
  return new THREE.Line(geometry, material);
}

export function buildMarker(lat, lon, altKm, color, radiusUnits = 0.07) {
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(radiusUnits, 12, 8),
    new THREE.MeshBasicMaterial({ color }),
  );
  latLonAltToVector3(lat, lon, altKm, marker.position);
  return marker;
}

function makeGlowTexture() {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(255,255,255,0.45)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  return texture;
}

/**
 * Prominent asset marker: bright core + additive glow halo + orbit-plane
 * ring, so the user's simulated position is findable at a glance.
 */
export function buildUserMarker(lat, lon, altKm, color = 0x6eb4ff) {
  const group = new THREE.Group();

  const core = new THREE.Mesh(
    new THREE.SphereGeometry(0.11, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  group.add(core);

  const glow = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: makeGlowTexture(),
      color,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  glow.scale.set(1.2, 1.2, 1);
  group.add(glow);

  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.2, 0.24, 32),
    new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.8 }),
  );
  group.add(ring);

  latLonAltToVector3(lat, lon, altKm, group.position);
  // Face the ring outward along the radial direction
  ring.lookAt(group.position.clone().multiplyScalar(2));
  return group;
}

/** Recursively disposes every geometry/material/texture under an Object3D. */
export function disposeObject(root) {
  root.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    if (node.material) {
      if (node.material.map) node.material.map.dispose();
      node.material.dispose();
    }
  });
}
