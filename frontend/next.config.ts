import type { NextConfig } from "next";

const INGESTION_API_URL = process.env.INGESTION_API_URL || "http://localhost:8003";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${INGESTION_API_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
