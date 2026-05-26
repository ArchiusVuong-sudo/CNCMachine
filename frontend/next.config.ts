import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: { ignoreBuildErrors: true },
  // pdfjs-dist references `require("canvas")` in a Node-only branch; alias it to
  // an empty stub so the browser bundle resolves (the path never runs client-side).
  turbopack: {
    resolveAlias: {
      canvas: "./empty-module.js",
    },
  },
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}),
  allowedDevOrigins: [
    "*.ngrok-free.app",
    "*.ngrok.io",
    "*.ngrok.app",
    "*.ngrok-free.dev",
  ],
};

export default nextConfig;
