import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: { ignoreBuildErrors: true },
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}),
  allowedDevOrigins: [
    "*.ngrok-free.app",
    "*.ngrok.io",
    "*.ngrok.app",
    "*.ngrok-free.dev",
  ],
};

export default nextConfig;
