// Copies runtime assets that must be served statically from /public:
//   - occt-import-js.js     (OCCT emscripten glue — loaded via <script> tag, not
//                            bundled, so its node-builtin branches never reach
//                            the Turbopack/webpack graph)
//   - occt-import-js.wasm   (OCCT WASM kernel used by the 3D STEP viewer)
//   - pdf.worker.min.js     (PDF.js worker used by the 2D drawing viewer)
//
// The 3D viewer injects `/occt-import-js.js` then calls the resulting global
// with `locateFile(() => "/occt-import-js.wasm")`; the PDF viewer sets
// `GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js"`, so all three files
// have to live in public/. Runs on postinstall so a fresh `npm install`
// (locally or on the pod) reproduces them. Tolerant by design: a missing
// source is logged, not fatal — the app still boots, the viewer just degrades.
import { existsSync, mkdirSync, copyFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const nm = join(root, "node_modules");
const publicDir = join(root, "public");

/** First existing path from a candidate list, else null. */
function firstExisting(paths) {
  for (const p of paths) if (existsSync(p)) return p;
  return null;
}

const jobs = [
  {
    label: "OCCT glue",
    src: firstExisting([
      join(nm, "occt-import-js", "dist", "occt-import-js.js"),
      join(nm, "occt-import-js", "occt-import-js.js"),
    ]),
    dest: join(publicDir, "occt-import-js.js"),
  },
  {
    label: "OCCT wasm",
    src: firstExisting([
      join(nm, "occt-import-js", "dist", "occt-import-js.wasm"),
      join(nm, "occt-import-js", "occt-import-js.wasm"),
    ]),
    dest: join(publicDir, "occt-import-js.wasm"),
  },
  {
    label: "PDF.js worker",
    src: firstExisting([
      join(nm, "pdfjs-dist", "build", "pdf.worker.min.js"),
      join(nm, "pdfjs-dist", "build", "pdf.worker.js"),
      join(nm, "pdfjs-dist", "legacy", "build", "pdf.worker.min.js"),
    ]),
    dest: join(publicDir, "pdf.worker.min.js"),
  },
];

try {
  if (!existsSync(publicDir)) mkdirSync(publicDir, { recursive: true });
  for (const job of jobs) {
    if (!job.src) {
      console.warn(`[copy-assets] ${job.label}: source not found (skipping) — viewer will degrade`);
      continue;
    }
    copyFileSync(job.src, job.dest);
    console.log(`[copy-assets] ${job.label}: ${job.src} -> ${job.dest}`);
  }
} catch (err) {
  console.warn(`[copy-assets] non-fatal error: ${err?.message ?? err}`);
}
