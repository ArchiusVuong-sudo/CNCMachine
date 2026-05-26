"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useRef, useState, useCallback } from "react";
import * as THREE from "three";
import { Box, Loader2, AlertCircle, RotateCcw, ZoomIn, ZoomOut, Scissors, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { getOcctInstance } from "./occt-loader";

interface StepViewerProps {
  fileUrl: string | null;
  title?: string;
}

const BG_COLOR = 0xf8fafc;        // slate-50
const GRID_MAJOR = 0xcbd5e1;      // slate-300
const GRID_MINOR = 0xe2e8f0;      // slate-200
const MESH_COLOR = 0x6b7d96;      // machined steel blue-grey

export function StepViewer({ fileUrl, title }: StepViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const animationIdRef = useRef<number | null>(null);
  const clippingPlaneRef = useRef<THREE.Plane | null>(null);
  const isInitializedRef = useRef(false);
  const pendingFileUrlRef = useRef<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelLoaded, setModelLoaded] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [clippingEnabled, setClippingEnabled] = useState(false);
  const [clippingPosition, setClippingPosition] = useState([50]);
  const [isVisible, setIsVisible] = useState(false);
  const previousMouseRef = useRef({ x: 0, y: 0 });
  const modelBoundsRef = useRef<{ min: number; max: number }>({ min: -5, max: 5 });

  // Fully dispose the WebGL context so we don't leak contexts across remounts.
  const cleanup = useCallback(() => {
    if (animationIdRef.current) {
      cancelAnimationFrame(animationIdRef.current);
      animationIdRef.current = null;
    }
    if (sceneRef.current) {
      while (sceneRef.current.children.length > 0) {
        const child = sceneRef.current.children[0];
        sceneRef.current.remove(child);
        if (child instanceof THREE.Mesh) {
          child.geometry?.dispose();
          const mats = Array.isArray(child.material) ? child.material : [child.material];
          mats.forEach((m) => m?.dispose());
        }
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
    setModelLoaded(false);
  }, []);

  // Only spin up WebGL when the viewport is actually on screen.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => setIsVisible(entries[0]?.isIntersecting ?? false),
      { threshold: 0.1 },
    );
    observer.observe(container);
    return () => {
      observer.disconnect();
      cleanup();
    };
  }, [cleanup]);

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
      camera.position.set(5, 5, 5);
      camera.lookAt(0, 0, 0);
      cameraRef.current = camera;

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
        if (rendererRef.current && sceneRef.current && cameraRef.current) {
          rendererRef.current.render(sceneRef.current, cameraRef.current);
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
  }, []);

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
    if (!sceneRef.current) return;
    setLoading(true);
    setError(null);
    setModelLoaded(false);
    setClippingEnabled(false);
    setClippingPosition([50]);

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
        modelRef.current.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.geometry.dispose();
            const mats = Array.isArray(child.material) ? child.material : [child.material];
            mats.forEach((m) => m?.dispose());
          }
        });
      }

      const group = new THREE.Group();
      for (const mesh of result.meshes) {
        if (!mesh.attributes?.position?.array) continue;
        const geometry = new THREE.BufferGeometry();
        const posArray = mesh.attributes.position.array;
        geometry.setAttribute("position", new THREE.BufferAttribute(
          posArray instanceof Float32Array ? posArray : new Float32Array(posArray), 3));
        if (mesh.attributes.normal?.array) {
          const n = mesh.attributes.normal.array;
          geometry.setAttribute("normal", new THREE.BufferAttribute(
            n instanceof Float32Array ? n : new Float32Array(n), 3));
        } else {
          geometry.computeVertexNormals();
        }
        if (mesh.index?.array) {
          const idx = mesh.index.array;
          geometry.setIndex(new THREE.BufferAttribute(
            idx instanceof Uint32Array ? idx : new Uint32Array(idx), 1));
        }
        let color = MESH_COLOR;
        if (mesh.color && mesh.color.length >= 3) {
          color = new THREE.Color(mesh.color[0], mesh.color[1], mesh.color[2]).getHex();
        }
        const material = new THREE.MeshPhongMaterial({ color, side: THREE.DoubleSide, flatShading: false, shininess: 30 });
        group.add(new THREE.Mesh(geometry, material));
      }

      // Center + scale to a comfortable viewing box.
      const box = new THREE.Box3().setFromObject(group);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 0) group.scale.setScalar(4 / maxDim);
      group.position.sub(center.multiplyScalar(group.scale.x));

      const scaledBox = new THREE.Box3().setFromObject(group);
      modelBoundsRef.current = { min: scaledBox.min.y, max: scaledBox.max.y };

      sceneRef.current.add(group);
      modelRef.current = group;

      if (cameraRef.current) {
        cameraRef.current.position.set(5, 5, 5);
        cameraRef.current.lookAt(0, 0, 0);
      }
      setModelLoaded(true);
    } catch (err) {
      console.error("StepViewer: error loading STEP file:", err);
      setError(err instanceof Error ? err.message : "Failed to load 3D model");
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Mouse / wheel orbit + zoom ────────────────────────────────────────────
  const handleMouseDown = (e: React.MouseEvent) => {
    if (!modelLoaded) return;
    setIsDragging(true);
    previousMouseRef.current = { x: e.clientX, y: e.clientY };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !modelRef.current) return;
    const dx = e.clientX - previousMouseRef.current.x;
    const dy = e.clientY - previousMouseRef.current.y;
    modelRef.current.rotation.y += dx * 0.01;
    modelRef.current.rotation.x += dy * 0.01;
    previousMouseRef.current = { x: e.clientX, y: e.clientY };
  };
  const handleMouseUp = () => setIsDragging(false);
  const handleWheel = (e: React.WheelEvent) => {
    if (!cameraRef.current || !modelLoaded) return;
    const newZ = cameraRef.current.position.z + e.deltaY * 0.01;
    cameraRef.current.position.z = Math.max(2, Math.min(20, newZ));
  };
  const handleZoomIn = () => { if (cameraRef.current) cameraRef.current.position.z = Math.max(2, cameraRef.current.position.z - 1); };
  const handleZoomOut = () => { if (cameraRef.current) cameraRef.current.position.z = Math.min(20, cameraRef.current.position.z + 1); };
  const handleResetView = () => {
    if (cameraRef.current) { cameraRef.current.position.set(5, 5, 5); cameraRef.current.lookAt(0, 0, 0); }
    if (modelRef.current) modelRef.current.rotation.set(0, 0, 0);
  };

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

  // Init scene when visible; tear down when hidden.
  useEffect(() => {
    if (!isVisible) {
      if (isInitializedRef.current) cleanup();
      return;
    }
    const t = setTimeout(() => {
      const ok = initScene();
      if (ok && pendingFileUrlRef.current) loadStepFile(pendingFileUrlRef.current);
    }, 50);
    return () => clearTimeout(t);
  }, [isVisible, initScene, cleanup, loadStepFile]);

  // Load STEP when URL changes (or defer until the scene is ready).
  useEffect(() => {
    if (!fileUrl) { pendingFileUrlRef.current = null; return; }
    if (isInitializedRef.current && isVisible) loadStepFile(fileUrl);
    else pendingFileUrlRef.current = fileUrl;
  }, [fileUrl, isVisible, loadStepFile]);

  const showPlaceholder = !fileUrl;

  return (
    <div className="relative h-full w-full">
      {modelLoaded && !loading && (
        <div className="absolute right-3 top-3 z-10 flex gap-1.5">
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant={clippingEnabled ? "default" : "outline"}
                size="icon"
                className="h-8 w-8 bg-background/90 backdrop-blur-sm"
                title="Cross section"
              >
                <Scissors className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-52 p-3" side="bottom" align="end">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">Cross section</span>
                  <Button
                    variant={clippingEnabled ? "default" : "outline"}
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => setClippingEnabled(!clippingEnabled)}
                  >
                    {clippingEnabled ? "On" : "Off"}
                  </Button>
                </div>
                {clippingEnabled && (
                  <div className="space-y-2">
                    <span className="text-xs text-muted-foreground">Cut position</span>
                    <Slider value={clippingPosition} onValueChange={setClippingPosition} min={0} max={100} step={1} />
                  </div>
                )}
              </div>
            </PopoverContent>
          </Popover>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={handleZoomIn} title="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={handleZoomOut} title="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={handleResetView} title="Reset view">
            <RotateCcw className="h-4 w-4" />
          </Button>
          {fileUrl && (
            <Button asChild variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" title="Open raw STEP">
              <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
            </Button>
          )}
        </div>
      )}

      {title && !showPlaceholder && (
        <div className="absolute left-3 top-3 z-10 rounded-md bg-background/90 px-2 py-1 text-xs text-muted-foreground backdrop-blur-sm">
          {title}
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="text-sm text-muted-foreground">Loading 3D model…</span>
          </div>
        </div>
      )}

      {error && !loading && !showPlaceholder && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 px-4 text-center backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <span className="text-sm text-destructive">{error}</span>
          </div>
        </div>
      )}

      {showPlaceholder && !loading && (
        <div className="viewport-grid absolute inset-0 z-20 flex flex-col items-center justify-center">
          <Box className="mb-2 h-12 w-12 text-muted-foreground/50" />
          <span className="text-sm text-muted-foreground">No CAD model available</span>
        </div>
      )}

      <div
        ref={containerRef}
        className="h-full w-full overflow-hidden"
        style={{ cursor: modelLoaded ? (isDragging ? "grabbing" : "grab") : "default" }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      />
    </div>
  );
}
