import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hides the dev-mode route indicator badge (bottom-left "N" circle) --
  // still surfaces real compile/runtime errors, just not this indicator.
  devIndicators: false,
};

export default nextConfig;
