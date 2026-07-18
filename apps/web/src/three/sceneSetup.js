import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export const EARTH_RADIUS_KM = 6378.137;
export const KM_TO_UNITS = 1 / 1000; // 1 scene unit == 1000 km

const SUN_UPDATE_MS = 60_000;

/**
 * Approximate subsolar direction in the Earth-fixed frame for a given time:
 * solar declination (±23.44° seasonal cosine) + hour angle (subsolar
 * longitude where local solar time is noon). Ignores the equation of time
 * (±16 min ≈ ±4° — irrelevant at this visual scale).
 * Returns a unit vector in the same axes as orbitPath.latLonAltToVector3.
 */
function sunDirection(date = new Date(), target = new THREE.Vector3()) {
  const startOfYear = Date.UTC(date.getUTCFullYear(), 0, 0);
  const dayOfYear = (date.getTime() - startOfYear) / 86_400_000;
  const declDeg = -23.44 * Math.cos(((2 * Math.PI) / 365) * (dayOfYear + 10));

  const utcHours =
    date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const subsolarLonDeg = (12 - utcHours) * 15;

  const lat = THREE.MathUtils.degToRad(declDeg);
  const lon = THREE.MathUtils.degToRad(subsolarLonDeg);
  return target.set(
    Math.cos(lat) * Math.cos(lon),
    Math.sin(lat),
    -Math.cos(lat) * Math.sin(lon),
  );
}

/**
 * Builds the static scene: camera, renderer, starfield, OrbitControls, and
 * a realistic Earth — Blue Marble day texture lit by a directional "sun"
 * placed at the real current subsolar point, with NASA Black Marble city
 * lights shader-gated to the night side. Both textures are bundled at
 * /textures/ (no runtime CDN dependency).
 *
 * Returns { scene, camera, renderer, controls, dispose }. dispose() is a
 * full synchronous teardown (safe under React StrictMode double-mount).
 */
export function createScene(container) {
  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(
    45,
    container.clientWidth / container.clientHeight,
    0.1,
    1000,
  );
  camera.position.set(0, 6, 17);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  // Dim ambient so the night hemisphere stays genuinely dark and the city
  // lights carry it; the sun does the day-side work.
  scene.add(new THREE.AmbientLight(0x334455, 0.55));
  const sunDir = sunDirection();
  const sun = new THREE.DirectionalLight(0xffffff, 2.6);
  sun.position.copy(sunDir).multiplyScalar(50);
  scene.add(sun);

  // Textured Earth. UV alignment: three's SphereGeometry puts the texture's
  // center meridian (lon 0) on +x, matching latLonAltToVector3 in orbitPath.js.
  const earthRadiusUnits = EARTH_RADIUS_KM * KM_TO_UNITS;
  const loader = new THREE.TextureLoader();
  const dayTexture = loader.load("/textures/earth_atmos_2048.jpg");
  dayTexture.colorSpace = THREE.SRGBColorSpace;
  const nightTexture = loader.load("/textures/earth_night_2048.jpg");
  nightTexture.colorSpace = THREE.SRGBColorSpace;

  const earthMaterial = new THREE.MeshPhongMaterial({
    map: dayTexture,
    shininess: 14,
    specular: 0x222933,
    emissive: 0xffffff,
    emissiveMap: nightTexture,
    emissiveIntensity: 1.15,
  });
  // Gate the emissive city lights to the night hemisphere: fade them out as
  // the surface normal turns toward the sun (smooth band across the
  // terminator). sunDirection is passed in world space and rotated into
  // view space here because Phong's `normal` is a view-space vector.
  earthMaterial.onBeforeCompile = (shader) => {
    shader.uniforms.uSunDirection = { value: sunDir };
    shader.fragmentShader =
      "uniform vec3 uSunDirection;\n" +
      shader.fragmentShader.replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
        vec3 sunDirView = normalize((viewMatrix * vec4(uSunDirection, 0.0)).xyz);
        float dayness = dot(normalize(normal), sunDirView);
        totalEmissiveRadiance *= smoothstep(0.12, -0.12, dayness);`,
      );
    earthMaterial.userData.shader = shader;
  };

  const earth = new THREE.Mesh(
    new THREE.SphereGeometry(earthRadiusUnits, 64, 48),
    earthMaterial,
  );
  scene.add(earth);

  // Keep the terminator tracking real time while the view stays open.
  const sunTimer = setInterval(() => {
    sunDirection(new Date(), sunDir);
    sun.position.copy(sunDir).multiplyScalar(50);
    // uSunDirection uniform holds a reference to sunDir — already updated.
  }, SUN_UPDATE_MS);

  // Starfield: random points on a distant shell, well outside orbit range.
  const starCount = 1800;
  const starPositions = new Float32Array(starCount * 3);
  for (let i = 0; i < starCount; i++) {
    const r = 120 + Math.random() * 240;
    const theta = Math.acos(2 * Math.random() - 1);
    const phi = Math.random() * Math.PI * 2;
    starPositions[i * 3] = r * Math.sin(theta) * Math.cos(phi);
    starPositions[i * 3 + 1] = r * Math.cos(theta);
    starPositions[i * 3 + 2] = r * Math.sin(theta) * Math.sin(phi);
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
  const starMaterial = new THREE.PointsMaterial({
    color: 0xdde6f5,
    size: 0.5,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
  });
  const stars = new THREE.Points(starGeometry, starMaterial);
  scene.add(stars);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = earthRadiusUnits * 1.15;
  controls.maxDistance = 80;

  const onResize = () => {
    if (!container.clientWidth || !container.clientHeight) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  };
  window.addEventListener("resize", onResize);

  function dispose() {
    clearInterval(sunTimer);
    window.removeEventListener("resize", onResize);
    controls.dispose();
    earth.geometry.dispose();
    earthMaterial.dispose();
    dayTexture.dispose();
    nightTexture.dispose();
    starGeometry.dispose();
    starMaterial.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode === container) {
      container.removeChild(renderer.domElement);
    }
  }

  return { scene, camera, renderer, controls, dispose };
}
