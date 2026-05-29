/**
 * Pure Three.js helpers for the STEP viewer — geometry construction, framing,
 * camera math, projection, and disposal. No React, no refs: these take plain
 * THREE objects and return data (or mutate the object you hand them), so the
 * imperative orchestration in `useStepViewer` stays thin and testable.
 */
import * as THREE from "three";

export const BG_COLOR = 0xf8fafc;        // slate-50
export const GRID_MAJOR = 0xcbd5e1;      // slate-300
export const GRID_MINOR = 0xe2e8f0;      // slate-200
export const MESH_COLOR = 0x6b7d96;      // machined steel blue-grey
export const BBOX_COLOR = 0x3b82f6;      // brand blue
export const MEASURE_COLOR = 0xef4444;   // red for measure markers

// Orbit-camera limits/defaults. The camera always *looks at the part centre*
// and zoom dollies along that view axis (radius), so framing never drifts.
export const MIN_RADIUS = 2.2;
export const MAX_RADIUS = 60;
export const DEFAULT_THETA = Math.PI / 4;                 // 45° azimuth → isometric
export const DEFAULT_PHI = Math.acos(1 / Math.sqrt(3));   // ~54.7° polar → isometric

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Camera orbit: position = target + spherical(radius, theta, phi). */
export interface Spherical {
  radius: number;
  theta: number;
  phi: number;
}

/** Real-world (pre-scale) dimensions in mm, sorted L ≥ W ≥ H. */
export interface Dims {
  l: number;
  w: number;
  h: number;
}

/** Minimal shape of an occt-import-js mesh entry. */
interface OcctMesh {
  attributes?: {
    position?: { array?: ArrayLike<number> };
    normal?: { array?: ArrayLike<number> };
  };
  index?: { array?: ArrayLike<number> };
  color?: number[];
}

/** Place the camera from an orbit and aim it at the target. */
export function positionCamera(camera: THREE.PerspectiveCamera, target: THREE.Vector3, s: Spherical): void {
  camera.position.set(
    target.x + s.radius * Math.sin(s.phi) * Math.sin(s.theta),
    target.y + s.radius * Math.cos(s.phi),
    target.z + s.radius * Math.sin(s.phi) * Math.cos(s.theta),
  );
  camera.lookAt(target);
}

/** Project a world point to 2D screen px relative to a container element. */
export function projectToScreen(
  worldPos: THREE.Vector3,
  camera: THREE.Camera,
  container: HTMLElement,
): { x: number; y: number } {
  const vec = worldPos.clone().project(camera);
  const rect = container.getBoundingClientRect();
  return {
    x: ((vec.x + 1) / 2) * rect.width,
    y: ((-vec.y + 1) / 2) * rect.height,
  };
}

/** Dispose a mesh's geometry and material(s). */
export function disposeMesh(mesh: THREE.Mesh): void {
  mesh.geometry?.dispose();
  const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  mats.forEach((m) => m?.dispose());
}

/** Build a THREE.Group from occt-import-js meshes; returns the group + ordered
 *  mesh list (matching the OCCT result order, used for component isolation). */
export function buildMeshGroup(meshes: OcctMesh[]): { group: THREE.Group; meshList: THREE.Mesh[] } {
  const group = new THREE.Group();
  const meshList: THREE.Mesh[] = [];

  for (const mesh of meshes) {
    const posArray = mesh.attributes?.position?.array;
    if (!posArray) continue;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(
      posArray instanceof Float32Array ? posArray : new Float32Array(posArray), 3));

    const normalArray = mesh.attributes?.normal?.array;
    if (normalArray) {
      geometry.setAttribute("normal", new THREE.BufferAttribute(
        normalArray instanceof Float32Array ? normalArray : new Float32Array(normalArray), 3));
    } else {
      geometry.computeVertexNormals();
    }

    const idxArray = mesh.index?.array;
    if (idxArray) {
      geometry.setIndex(new THREE.BufferAttribute(
        idxArray instanceof Uint32Array ? idxArray : new Uint32Array(idxArray), 1));
    }

    let color = MESH_COLOR;
    if (mesh.color && mesh.color.length >= 3) {
      color = new THREE.Color(mesh.color[0], mesh.color[1], mesh.color[2]).getHex();
    }
    const material = new THREE.MeshPhongMaterial({ color, side: THREE.DoubleSide, flatShading: false, shininess: 30 });
    const threeMesh = new THREE.Mesh(geometry, material);
    group.add(threeMesh);
    meshList.push(threeMesh);
  }

  return { group, meshList };
}

/** Pre-scale bounding-box dimensions in mm (STEP is in mm), sorted L ≥ W ≥ H. */
export function realWorldDims(group: THREE.Object3D): Dims {
  const size = new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3());
  const dims = [size.x, size.y, size.z].sort((a, b) => b - a);
  return { l: dims[0], w: dims[1], h: dims[2] };
}

/** The framing of a freshly-loaded model: how it was scaled, its clip bounds,
 *  and the orbit target/radius "Reset" returns to. */
export interface FrameResult {
  /** scene units = mm * scaleFactor (used to convert measured distances back). */
  scaleFactor: number;
  /** Y-extent of the scaled model, for the cross-section clip plane. */
  bounds: { min: number; max: number };
  /** Orbit target (the part centre). */
  target: THREE.Vector3;
  /** Orbit radius that frames the part to ~85% of the vertical FOV. */
  radius: number;
}

/**
 * Center the group at the origin, scale it into a comfortable viewing box, and
 * compute the framing the camera should reset to. Mutates `group` (scale +
 * position); reads `camera.fov`.
 */
export function frameModel(group: THREE.Group, camera: THREE.PerspectiveCamera): FrameResult {
  const box = new THREE.Box3().setFromObject(group);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  if (maxDim > 0) group.scale.setScalar(4 / maxDim);
  group.position.sub(center.multiplyScalar(group.scale.x));
  const scaleFactor = maxDim > 0 ? 4 / maxDim : 1;

  const scaledBox = new THREE.Box3().setFromObject(group);
  const bounds = { min: scaledBox.min.y, max: scaledBox.max.y };

  const sphere = scaledBox.getBoundingSphere(new THREE.Sphere());
  const fov = (camera.fov * Math.PI) / 180;
  const radius = clamp((sphere.radius / Math.sin(fov / 2)) * 1.15, MIN_RADIUS, MAX_RADIUS);
  return { scaleFactor, bounds, target: sphere.center.clone(), radius };
}
