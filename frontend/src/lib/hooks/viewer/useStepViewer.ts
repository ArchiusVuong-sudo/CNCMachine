"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Headless STEP viewer engine. Owns the WebGL lifecycle (scene/camera/renderer),
 * model loading, orbit/zoom, component isolation, the bounding-box overlay with
 * editable dimensions, the point-to-point measure tool, and the cross-section
 * clip plane. Returns refs + grouped state/actions; `step-viewer.tsx` is pure JSX
 * over this. The geometry/camera math lives in `@/lib/three/step-scene`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { getOcctInstance } from "@/components/viewport/occt-loader";
import type { ViewportComponentInfo } from "@/components/viewport/viewport";
import {
  BG_COLOR, GRID_MAJOR, GRID_MINOR, BBOX_COLOR, MEASURE_COLOR,
  MIN_RADIUS, MAX_RADIUS, DEFAULT_THETA, DEFAULT_PHI, clamp,
  positionCamera, projectToScreen, disposeMesh, buildMeshGroup, realWorldDims, frameModel,
  type Spherical,
} from "@/lib/three/step-scene";

interface UseStepViewerArgs {
  fileUrl: string | null;
  components?: ViewportComponentInfo[];
  selectedIndex?: number | null;
}

type Dim = "l" | "w" | "h";
type ScreenPos = { x: number; y: number } | null;

/** A placed measure point: its scene-space position and the marker sphere. */
interface MeasurePoint {
  position: THREE.Vector3;
  marker: THREE.Mesh;
}

export function useStepViewer({ fileUrl, components, selectedIndex }: UseStepViewerArgs) {
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const animationIdRef = useRef<number | null>(null);
  const clippingPlaneRef = useRef<THREE.Plane | null>(null);
  const isInitializedRef = useRef(false);
  const pendingFileUrlRef = useRef<string | null>(null);
  // Mirrors `isVisible` for the RAF loop so it can pause work off-screen
  // without tearing down the WebGL context + re-parsing the STEP file.
  const visibleRef = useRef(false);
  // URL of the model currently resident in the scene — guards against
  // re-parsing the same file when the viewer scrolls back into view.
  const loadedUrlRef = useRef<string | null>(null);
  // True once the "no overlay labels" state has been pushed, so the RAF loop
  // stops calling setState every frame when there's nothing to project.
  const overlayEmptyRef = useRef(false);

  // Real-world (pre-scale) dimensions in mm
  const realWorldDimsRef = useRef<{ l: number; w: number; h: number } | null>(null);
  // Scale factor: scene units = mm * scaleFactor
  const scaleFactorRef = useRef<number>(1);

  // Per-mesh original materials for component isolation
  const originalMaterialsRef = useRef<Map<THREE.Mesh, THREE.Material | THREE.Material[]>>(new Map());
  // Ordered mesh list (matches OCCT result.meshes order)
  const meshListRef = useRef<THREE.Mesh[]>([]);

  // BBox toggle
  const bboxHelperRef = useRef<THREE.LineSegments | null>(null);
  const dimLabelWorldPosRef = useRef<{ l: THREE.Vector3; w: THREE.Vector3; h: THREE.Vector3 } | null>(null);

  // Measure tool
  const measurePointsRef = useRef<MeasurePoint[]>([]);
  const measureLineRef = useRef<THREE.Line | null>(null);
  const measureLabelWorldPosRef = useRef<THREE.Vector3 | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelLoaded, setModelLoaded] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [clippingEnabled, setClippingEnabled] = useState(false);
  const [clippingPosition, setClippingPosition] = useState([50]);
  const [isVisible, setIsVisible] = useState(false);
  const previousMouseRef = useRef({ x: 0, y: 0 });
  const modelBoundsRef = useRef<{ min: number; max: number }>({ min: -5, max: 5 });

  const [bboxVisible, setBboxVisible] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);
  const [measureCount, setMeasureCount] = useState(0); // 0, 1, or 2
  const [measureDistMm, setMeasureDistMm] = useState<number | null>(null);
  const measureModeRef = useRef(false); // sync ref for event handlers

  // Editable dimension label values
  const [dimValues, setDimValues] = useState<{ l: number; w: number; h: number }>({ l: 0, w: 0, h: 0 });
  const [editingDim, setEditingDim] = useState<Dim | null>(null);
  const [editInput, setEditInput] = useState("");

  // Overlay label screen positions (updated in RAF)
  const [dimLabelPos, setDimLabelPos] = useState<{ l: ScreenPos; w: ScreenPos; h: ScreenPos }>({ l: null, w: null, h: null });
  const [measureLabelPos, setMeasureLabelPos] = useState<ScreenPos>(null);

  // Orbit state: camera = target + spherical(radius, theta, phi). The part is
  // centred at the origin on load, so the target stays at (0,0,0). `defaultRadius`
  // is recomputed per model so "Reset" reframes whatever is loaded.
  const targetRef = useRef(new THREE.Vector3(0, 0, 0));
  const sphericalRef = useRef<Spherical>({ radius: 9, theta: DEFAULT_THETA, phi: DEFAULT_PHI });
  const defaultRadiusRef = useRef(9);

  // Position the camera from the current orbit — the single source of camera truth.
  const applyCamera = useCallback(() => {
    if (cameraRef.current) positionCamera(cameraRef.current, targetRef.current, sphericalRef.current);
  }, []);

  // ── BBox helper ──────────────────────────────────────────────────────────────
  const removeBboxHelper = useCallback(() => {
    if (bboxHelperRef.current && sceneRef.current) {
      sceneRef.current.remove(bboxHelperRef.current);
      bboxHelperRef.current.geometry.dispose();
      (bboxHelperRef.current.material as THREE.Material).dispose();
      bboxHelperRef.current = null;
    }
    dimLabelWorldPosRef.current = null;
  }, []);

  const addBboxHelper = useCallback(() => {
    if (!modelRef.current || !sceneRef.current) return;
    removeBboxHelper();

    const box = new THREE.Box3().setFromObject(modelRef.current);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    const boxGeo = new THREE.BoxGeometry(size.x, size.y, size.z);
    const edges = new THREE.EdgesGeometry(boxGeo);
    boxGeo.dispose();
    const mat = new THREE.LineBasicMaterial({ color: BBOX_COLOR, linewidth: 1 });
    const lines = new THREE.LineSegments(edges, mat);
    lines.position.copy(center);
    sceneRef.current.add(lines);
    bboxHelperRef.current = lines;

    // Label world positions: L along X (bottom), W along Z (right), H along Y (front-right).
    const lPos = new THREE.Vector3(center.x, box.min.y - 0.15, center.z);
    const wPos = new THREE.Vector3(box.max.x + 0.15, box.min.y - 0.15, center.z);
    const hPos = new THREE.Vector3(box.max.x + 0.15, center.y, box.max.z);
    dimLabelWorldPosRef.current = { l: lPos, w: wPos, h: hPos };
  }, [removeBboxHelper]);

  // ── Measure helpers ──────────────────────────────────────────────────────────
  const clearMeasure = useCallback(() => {
    if (!sceneRef.current) return;
    for (const pt of measurePointsRef.current) {
      sceneRef.current.remove(pt.marker);
      pt.marker.geometry.dispose();
      (pt.marker.material as THREE.Material).dispose();
    }
    measurePointsRef.current = [];
    if (measureLineRef.current) {
      sceneRef.current.remove(measureLineRef.current);
      measureLineRef.current.geometry.dispose();
      (measureLineRef.current.material as THREE.Material).dispose();
      measureLineRef.current = null;
    }
    measureLabelWorldPosRef.current = null;
    setMeasureCount(0);
    setMeasureDistMm(null);
    setMeasureLabelPos(null);
  }, []);

  // ── Component isolation ───────────────────────────────────────────────────────
  const applyComponentIsolation = useCallback(() => {
    const meshes = meshListRef.current;
    if (meshes.length === 0) return;

    const comps = components ?? [];
    const sel = selectedIndex;

    // Restore originals first
    for (const mesh of meshes) {
      const orig = originalMaterialsRef.current.get(mesh);
      if (orig) {
        mesh.material = orig;
        if (Array.isArray(mesh.material)) {
          mesh.material.forEach((m) => { m.transparent = false; m.opacity = 1; });
        } else {
          (mesh.material as THREE.MeshPhongMaterial).transparent = false;
          (mesh.material as THREE.MeshPhongMaterial).opacity = 1;
        }
      }
    }

    // Only apply isolation if counts match and selectedIndex is a number
    if (typeof sel !== "number" || sel === null) return;
    const sorted = [...comps].sort((a, b) => a.component_index - b.component_index);
    if (sorted.length !== meshes.length) return;

    const selectedMeshIdx = sorted.findIndex((c) => c.component_index === sel);
    if (selectedMeshIdx === -1) return;

    for (let i = 0; i < meshes.length; i++) {
      const mesh = meshes[i];
      if (i === selectedMeshIdx) continue; // keep selected at full opacity

      const orig = originalMaterialsRef.current.get(mesh);
      if (!orig) continue;
      const origMat = Array.isArray(orig) ? orig[0] : orig;
      if (!origMat) continue;

      const dimMat = (origMat as THREE.MeshPhongMaterial).clone();
      dimMat.transparent = true;
      dimMat.opacity = 0.18;
      dimMat.color.set(0x999999);
      mesh.material = dimMat;
    }
  }, [components, selectedIndex]);

  // Re-apply isolation whenever selectedIndex or components changes
  useEffect(() => {
    if (modelLoaded) applyComponentIsolation();
  }, [selectedIndex, components, modelLoaded, applyComponentIsolation]);

  // ── Resolve real-world dims for bbox labels ───────────────────────────────────
  const getEffectiveDims = useCallback((): { l: number; w: number; h: number } => {
    const comps = components ?? [];
    const sel = selectedIndex;

    // (a) selected component bbox
    if (typeof sel === "number" && sel !== null) {
      const comp = comps.find((c) => c.component_index === sel);
      if (comp?.bbox) {
        const { length_mm, width_mm, height_mm } = comp.bbox;
        if (length_mm && width_mm && height_mm) return { l: length_mm, w: width_mm, h: height_mm };
      }
    }
    // (b) first component bbox
    if (comps.length > 0 && comps[0].bbox) {
      const { length_mm, width_mm, height_mm } = comps[0].bbox;
      if (length_mm && width_mm && height_mm) return { l: length_mm, w: width_mm, h: height_mm };
    }
    // (c) fall back to measured pre-scale mm dims
    if (realWorldDimsRef.current) return realWorldDimsRef.current;
    return { l: 0, w: 0, h: 0 };
  }, [components, selectedIndex]);

  // When bbox is toggled on or selectedIndex changes, refresh dim values
  useEffect(() => {
    if (bboxVisible) {
      setDimValues(getEffectiveDims());
      setEditingDim(null);
      if (modelRef.current) addBboxHelper();
    } else {
      removeBboxHelper();
    }
  }, [bboxVisible, selectedIndex, getEffectiveDims, addBboxHelper, removeBboxHelper]);

  // Fully dispose the WebGL context so we don't leak contexts across remounts.
  const cleanup = useCallback(() => {
    if (animationIdRef.current) {
      cancelAnimationFrame(animationIdRef.current);
      animationIdRef.current = null;
    }
    removeBboxHelper();
    if (sceneRef.current) {
      for (const pt of measurePointsRef.current) {
        sceneRef.current.remove(pt.marker);
        pt.marker.geometry.dispose();
        (pt.marker.material as THREE.Material).dispose();
      }
      measurePointsRef.current = [];
      if (measureLineRef.current) {
        sceneRef.current.remove(measureLineRef.current);
        measureLineRef.current.geometry.dispose();
        (measureLineRef.current.material as THREE.Material).dispose();
        measureLineRef.current = null;
      }

      while (sceneRef.current.children.length > 0) {
        const child = sceneRef.current.children[0];
        sceneRef.current.remove(child);
        if (child instanceof THREE.Mesh) disposeMesh(child);
      }
    }
    if (rendererRef.current) {
      rendererRef.current.dispose();
      rendererRef.current.forceContextLoss();
      const el = rendererRef.current.domElement;
      if (containerRef.current && el.parentNode === containerRef.current) {
        containerRef.current.removeChild(el);
      }
      rendererRef.current = null;
    }
    modelRef.current = null;
    sceneRef.current = null;
    cameraRef.current = null;
    clippingPlaneRef.current = null;
    isInitializedRef.current = false;
    loadedUrlRef.current = null;
    overlayEmptyRef.current = false;
    originalMaterialsRef.current.clear();
    meshListRef.current = [];
    measureLabelWorldPosRef.current = null;
    setMeasureCount(0);
    setMeasureDistMm(null);
    setMeasureLabelPos(null);
    setDimLabelPos({ l: null, w: null, h: null });
    setModelLoaded(false);
  }, [removeBboxHelper]);

  // Only spin up WebGL when the viewport is actually on screen.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const vis = entries[0]?.isIntersecting ?? false;
        visibleRef.current = vis;
        setIsVisible(vis);
      },
      { threshold: 0.1 },
    );
    observer.observe(container);
    return () => {
      observer.disconnect();
      cleanup();
    };
  }, [cleanup]);

  // The animate loop needs the latest overlay-position updater, but that depends
  // on state setters — store it in a ref so the loop always calls the latest.
  const updateOverlayPositionsRef = useRef<() => void>(() => {});

  useEffect(() => {
    updateOverlayPositionsRef.current = () => {
      const camera = cameraRef.current;
      const container = containerRef.current;
      if (!camera || !container) return;

      const hasDim = !!dimLabelWorldPosRef.current;
      const hasMeasure = !!measureLabelWorldPosRef.current;

      // Idle (no bbox, no active measure): push the cleared state exactly once,
      // then stay silent. Otherwise this would setState on every animation
      // frame and re-render the viewer ~60×/s — the main source of scroll jank.
      if (!hasDim && !hasMeasure) {
        if (!overlayEmptyRef.current) {
          overlayEmptyRef.current = true;
          setDimLabelPos({ l: null, w: null, h: null });
          setMeasureLabelPos(null);
        }
        return;
      }
      overlayEmptyRef.current = false;

      if (hasDim) {
        const w = dimLabelWorldPosRef.current!;
        setDimLabelPos({
          l: projectToScreen(w.l, camera, container),
          w: projectToScreen(w.w, camera, container),
          h: projectToScreen(w.h, camera, container),
        });
      } else {
        setDimLabelPos({ l: null, w: null, h: null });
      }

      if (hasMeasure) {
        setMeasureLabelPos(projectToScreen(measureLabelWorldPosRef.current!, camera, container));
      } else {
        setMeasureLabelPos(null);
      }
    };
  }, []);

  const initScene = useCallback(() => {
    if (!containerRef.current || isInitializedRef.current) return false;
    const container = containerRef.current;
    const width = container.clientWidth || 300;
    const height = container.clientHeight || 200;

    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(BG_COLOR);
      sceneRef.current = scene;

      const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
      cameraRef.current = camera;
      applyCamera();

      clippingPlaneRef.current = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.localClippingEnabled = true;
      container.appendChild(renderer.domElement);
      rendererRef.current = renderer;

      scene.add(new THREE.AmbientLight(0xffffff, 0.65));
      const l1 = new THREE.DirectionalLight(0xffffff, 0.85); l1.position.set(10, 10, 10); scene.add(l1);
      const l2 = new THREE.DirectionalLight(0xffffff, 0.4); l2.position.set(-10, -10, -10); scene.add(l2);
      const l3 = new THREE.DirectionalLight(0xffffff, 0.3); l3.position.set(0, 10, 0); scene.add(l3);
      scene.add(new THREE.GridHelper(10, 10, GRID_MAJOR, GRID_MINOR));

      const animate = () => {
        animationIdRef.current = requestAnimationFrame(animate);
        // Pause all work while off-screen — the context stays alive so
        // scrolling back into view resumes instantly (no STEP re-parse).
        if (visibleRef.current && rendererRef.current && sceneRef.current && cameraRef.current) {
          rendererRef.current.render(sceneRef.current, cameraRef.current);
          updateOverlayPositionsRef.current();
        }
      };
      animate();
      isInitializedRef.current = true;
      return true;
    } catch (err) {
      console.error("Failed to initialize WebGL:", err);
      setError("WebGL not available. Close other 3D viewers or refresh the page.");
      return false;
    }
  }, [applyCamera]);

  const updateClippingPlane = useCallback((position: number) => {
    if (!clippingPlaneRef.current) return;
    const { min, max } = modelBoundsRef.current;
    clippingPlaneRef.current.constant = min + (position / 100) * (max - min);
  }, []);

  const toggleClipping = useCallback((enabled: boolean) => {
    if (!modelRef.current || !clippingPlaneRef.current) return;
    modelRef.current.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        mats.forEach((mat) => {
          if (mat instanceof THREE.MeshPhongMaterial || mat instanceof THREE.MeshStandardMaterial) {
            mat.clippingPlanes = enabled ? [clippingPlaneRef.current!] : [];
            mat.clipShadows = enabled;
            mat.needsUpdate = true;
          }
        });
      }
    });
  }, []);

  useEffect(() => { toggleClipping(clippingEnabled); }, [clippingEnabled, toggleClipping]);
  useEffect(() => { if (clippingEnabled) updateClippingPlane(clippingPosition[0]); }, [clippingPosition, clippingEnabled, updateClippingPlane]);

  const loadStepFile = useCallback(async (url: string) => {
    if (!sceneRef.current || !cameraRef.current) return;
    setLoading(true);
    setError(null);
    setModelLoaded(false);
    setClippingEnabled(false);
    setClippingPosition([50]);
    setBboxVisible(false);
    setMeasureMode(false);
    measureModeRef.current = false;
    setMeasureCount(0);
    setMeasureDistMm(null);
    setMeasureLabelPos(null);
    setDimLabelPos({ l: null, w: null, h: null });
    removeBboxHelper();

    // Clean up any existing measure artifacts
    for (const pt of measurePointsRef.current) {
      sceneRef.current.remove(pt.marker);
      pt.marker.geometry.dispose();
      (pt.marker.material as THREE.Material).dispose();
    }
    measurePointsRef.current = [];
    if (measureLineRef.current) {
      sceneRef.current.remove(measureLineRef.current);
      measureLineRef.current.geometry.dispose();
      (measureLineRef.current.material as THREE.Material).dispose();
      measureLineRef.current = null;
    }
    measureLabelWorldPosRef.current = null;
    originalMaterialsRef.current.clear();
    meshListRef.current = [];

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Failed to fetch STEP file: ${response.status} ${response.statusText}`);
      const fileBuffer = new Uint8Array(await response.arrayBuffer());

      const occt = await getOcctInstance();
      const result = occt.ReadStepFile(fileBuffer, null);
      if (!result?.success) throw new Error("Failed to parse STEP file");
      if (!result.meshes || result.meshes.length === 0) throw new Error("No geometry found in STEP file");

      // Drop any previous model.
      if (modelRef.current && sceneRef.current) {
        sceneRef.current.remove(modelRef.current);
        modelRef.current.traverse((child) => { if (child instanceof THREE.Mesh) disposeMesh(child); });
      }

      const { group, meshList } = buildMeshGroup(result.meshes);

      // Pre-scale (mm) dims for bbox labels — capture before framing scales the group.
      realWorldDimsRef.current = realWorldDims(group);

      // Center + scale into the viewing box; capture framing for reset + measure.
      const frame = frameModel(group, cameraRef.current);
      scaleFactorRef.current = frame.scaleFactor;
      modelBoundsRef.current = frame.bounds;

      sceneRef.current.add(group);
      modelRef.current = group;
      meshListRef.current = meshList;

      // Store original materials for component isolation
      const matMap = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
      for (const mesh of meshList) {
        matMap.set(mesh, Array.isArray(mesh.material) ? [...mesh.material] : mesh.material);
      }
      originalMaterialsRef.current = matMap;

      // Frame the part; "Reset" returns to exactly this framing.
      targetRef.current.copy(frame.target);
      defaultRadiusRef.current = frame.radius;
      sphericalRef.current = { radius: frame.radius, theta: DEFAULT_THETA, phi: DEFAULT_PHI };
      applyCamera();
      loadedUrlRef.current = url;
      setModelLoaded(true);
    } catch (err) {
      console.error("StepViewer: error loading STEP file:", err);
      setError(err instanceof Error ? err.message : "Failed to load 3D model");
    } finally {
      setLoading(false);
    }
  }, [applyCamera, removeBboxHelper]);

  // Apply isolation after model loads
  useEffect(() => {
    if (modelLoaded) applyComponentIsolation();
  }, [modelLoaded, applyComponentIsolation]);

  // ── Mouse / wheel orbit + zoom ────────────────────────────────────────────
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (!modelLoaded || measureModeRef.current) return; // don't orbit in measure mode
    setIsDragging(true);
    previousMouseRef.current = { x: e.clientX, y: e.clientY };
  }, [modelLoaded]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !modelLoaded || measureModeRef.current) return;
    const dx = e.clientX - previousMouseRef.current.x;
    const dy = e.clientY - previousMouseRef.current.y;
    const s = sphericalRef.current;
    s.theta -= dx * 0.01;                                    // drag horizontally → orbit around the part
    s.phi = clamp(s.phi - dy * 0.01, 0.05, Math.PI - 0.05);  // clamp so we never flip over the poles
    applyCamera();
    previousMouseRef.current = { x: e.clientX, y: e.clientY };
  }, [isDragging, modelLoaded, applyCamera]);

  const onMouseUp = useCallback(() => {
    if (!measureModeRef.current) setIsDragging(false);
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!cameraRef.current || !modelLoaded) return;
    const s = sphericalRef.current;
    s.radius = clamp(s.radius * (1 + e.deltaY * 0.0015), MIN_RADIUS, MAX_RADIUS); // dolly along the view axis
    applyCamera();
  }, [modelLoaded, applyCamera]);

  const zoomIn = useCallback(() => {
    sphericalRef.current.radius = clamp(sphericalRef.current.radius * 0.85, MIN_RADIUS, MAX_RADIUS);
    applyCamera();
  }, [applyCamera]);

  const zoomOut = useCallback(() => {
    sphericalRef.current.radius = clamp(sphericalRef.current.radius * 1.18, MIN_RADIUS, MAX_RADIUS);
    applyCamera();
  }, [applyCamera]);

  const resetView = useCallback(() => {
    sphericalRef.current = { radius: defaultRadiusRef.current, theta: DEFAULT_THETA, phi: DEFAULT_PHI };
    if (modelRef.current) modelRef.current.rotation.set(0, 0, 0);
    applyCamera();
  }, [applyCamera]);

  // ── Measure click handler ─────────────────────────────────────────────────
  const onClick = useCallback((e: React.MouseEvent) => {
    if (!measureModeRef.current || !modelRef.current || !cameraRef.current || !sceneRef.current || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), cameraRef.current);

    const meshes: THREE.Mesh[] = [];
    modelRef.current.traverse((child) => { if (child instanceof THREE.Mesh) meshes.push(child); });

    const intersects = raycaster.intersectObjects(meshes, false);
    if (intersects.length === 0) return;

    const hitPoint = intersects[0].point.clone();

    if (measurePointsRef.current.length >= 2) clearMeasure(); // third click: clear and restart

    const sphereGeo = new THREE.SphereGeometry(0.05, 8, 8);
    const sphereMat = new THREE.MeshBasicMaterial({ color: MEASURE_COLOR });
    const marker = new THREE.Mesh(sphereGeo, sphereMat);
    marker.position.copy(hitPoint);
    sceneRef.current.add(marker);

    measurePointsRef.current.push({ position: hitPoint, marker });
    const count = measurePointsRef.current.length;
    setMeasureCount(count);

    if (count === 2) {
      const pts = [measurePointsRef.current[0].position, measurePointsRef.current[1].position];
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
      const lineMat = new THREE.LineBasicMaterial({ color: MEASURE_COLOR });
      const line = new THREE.Line(lineGeo, lineMat);
      sceneRef.current.add(line);
      measureLineRef.current = line;

      measureLabelWorldPosRef.current = new THREE.Vector3().addVectors(pts[0], pts[1]).multiplyScalar(0.5);

      const sceneDist = pts[0].distanceTo(pts[1]);
      const scaleFactor = scaleFactorRef.current;
      setMeasureDistMm(scaleFactor > 0 ? sceneDist / scaleFactor : sceneDist);
    }
  }, [clearMeasure]);

  // Resize handling.
  useEffect(() => {
    const handleResize = () => {
      if (!containerRef.current || !rendererRef.current || !cameraRef.current) return;
      const width = containerRef.current.clientWidth;
      const height = containerRef.current.clientHeight;
      if (width > 0 && height > 0) {
        cameraRef.current.aspect = width / height;
        cameraRef.current.updateProjectionMatrix();
        rendererRef.current.setSize(width, height);
      }
    };
    window.addEventListener("resize", handleResize);
    const t = setTimeout(handleResize, 100);
    return () => { window.removeEventListener("resize", handleResize); clearTimeout(t); };
  }, []);

  // Init the scene the first time it scrolls into view. We deliberately do NOT
  // tear down when it scrolls back out — the RAF loop pauses itself (via
  // `visibleRef`) and the model stays resident, so re-entry is instant instead
  // of re-fetching and re-parsing the STEP file. Full teardown is unmount-only
  // (the IntersectionObserver effect's cleanup).
  useEffect(() => {
    if (!isVisible || isInitializedRef.current) return;
    const t = setTimeout(() => {
      const ok = initScene();
      if (ok && pendingFileUrlRef.current) loadStepFile(pendingFileUrlRef.current);
    }, 50);
    return () => clearTimeout(t);
  }, [isVisible, initScene, loadStepFile]);

  // Load STEP when the URL changes (or defer until the scene is ready). Skip if
  // this exact URL is already resident, so a visibility flip never reloads it.
  useEffect(() => {
    if (!fileUrl) { pendingFileUrlRef.current = null; return; }
    if (loadedUrlRef.current === fileUrl) return;
    if (isInitializedRef.current && isVisible) loadStepFile(fileUrl);
    else pendingFileUrlRef.current = fileUrl;
  }, [fileUrl, isVisible, loadStepFile]);

  const toggleMeasure = useCallback(() => {
    const next = !measureModeRef.current;
    setMeasureMode(next);
    measureModeRef.current = next;
    if (!next) {
      clearMeasure();
      setIsDragging(false);
    }
  }, [clearMeasure]);

  const toggleBbox = useCallback(() => setBboxVisible((v) => !v), []);

  // ── Dimension label editing ───────────────────────────────────────────────
  const onDimDoubleClick = useCallback((dim: Dim) => {
    setEditingDim(dim);
    setEditInput(String(dimValues[dim].toFixed(1)));
  }, [dimValues]);

  const onDimEditCommit = useCallback(() => {
    setEditingDim((dim) => {
      if (dim) {
        const val = parseFloat(editInput);
        if (!isNaN(val) && val > 0) setDimValues((prev) => ({ ...prev, [dim]: val }));
      }
      return null;
    });
    setEditInput("");
  }, [editInput]);

  const onDimEditKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") onDimEditCommit();
    if (e.key === "Escape") { setEditingDim(null); setEditInput(""); }
  }, [onDimEditCommit]);

  const cursorStyle = measureMode
    ? "crosshair"
    : modelLoaded
      ? (isDragging ? "grabbing" : "grab")
      : "default";

  return {
    containerRef,
    overlayRef,
    loading,
    error,
    modelLoaded,
    cursorStyle,
    pointer: { onMouseDown, onMouseMove, onMouseUp, onWheel, onClick },
    view: { zoomIn, zoomOut, resetView },
    measure: {
      active: measureMode,
      toggle: toggleMeasure,
      count: measureCount,
      distMm: measureDistMm,
      labelPos: measureLabelPos,
    },
    bbox: {
      visible: bboxVisible,
      toggle: toggleBbox,
      dimValues,
      labelPos: dimLabelPos,
      editingDim,
      editInput,
      setEditInput,
      onDoubleClick: onDimDoubleClick,
      onEditCommit: onDimEditCommit,
      onEditKeyDown: onDimEditKeyDown,
    },
    section: {
      enabled: clippingEnabled,
      setEnabled: setClippingEnabled,
      position: clippingPosition,
      setPosition: setClippingPosition,
    },
  };
}
