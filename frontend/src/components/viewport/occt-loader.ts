"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Loads the OCCT emscripten glue from ``/public`` via a ``<script>`` tag and
 * returns an initialized OCCT instance.
 *
 * Why a script tag and not ``import("occt-import-js")``: the glue is an
 * emscripten UMD bundle whose Node branches reference ``fs`` / ``path`` /
 * ``crypto``. Pulling it into the Turbopack/webpack graph drags those
 * node-builtins in and breaks the browser build. Loading it as a classic
 * script sidesteps the bundler entirely — the file defines a global
 * ``window.occtimportjs`` factory, and the ``.wasm`` is fetched at runtime
 * via ``locateFile``. Both assets are produced by ``scripts/copy-assets.mjs``.
 *
 * The instance + in-flight promise are cached for the page lifetime so every
 * STEP viewer on the page reuses one WASM module.
 */

declare global {
  interface Window {
    occtimportjs?: (opts?: Record<string, unknown>) => Promise<any>;
  }
}

const GLUE_SRC = "/occt-import-js.js";
const WASM_SRC = "/occt-import-js.wasm";
const SCRIPT_ID = "occt-import-js-glue";

let occtInstance: any = null;
let occtLoading: Promise<any> | null = null;

function loadGlue(): Promise<(opts?: Record<string, unknown>) => Promise<any>> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("OCCT can only be loaded in the browser"));
      return;
    }
    if (window.occtimportjs) {
      resolve(window.occtimportjs);
      return;
    }

    const onReady = () => {
      if (window.occtimportjs) resolve(window.occtimportjs);
      else reject(new Error("OCCT glue loaded but window.occtimportjs is missing"));
    };

    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", onReady);
      existing.addEventListener("error", () => reject(new Error("Failed to load OCCT glue")));
      return;
    }

    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = GLUE_SRC;
    script.async = true;
    script.onload = onReady;
    script.onerror = () => reject(new Error("Failed to load OCCT glue"));
    document.head.appendChild(script);
  });
}

/** Resolve (and cache) a ready OCCT instance. Throws if WASM init fails. */
export async function getOcctInstance(): Promise<any> {
  if (occtInstance) return occtInstance;
  if (occtLoading) return occtLoading;

  occtLoading = (async () => {
    const factory = await loadGlue();
    const instance = await factory({
      locateFile: (path: string) => (path.endsWith(".wasm") ? WASM_SRC : path),
    });
    occtInstance = instance;
    return instance;
  })();

  try {
    return await occtLoading;
  } catch (err) {
    occtLoading = null; // allow a later retry
    throw err;
  }
}
