// Stub for optional Node-only modules pulled into browser bundles.
//
// pdfjs-dist's UMD build statically references `require("canvas")` inside a
// Node-only code path (NodeCanvasFactory). The browser never executes it, but
// Turbopack/webpack still try to resolve the specifier at build time. Aliasing
// `canvas` to this empty module satisfies the bundler without shipping it.
module.exports = {};
