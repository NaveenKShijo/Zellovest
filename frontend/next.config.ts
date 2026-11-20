import type { NextConfig } from "next";

const INGESTION_API_URL = process.env.INGESTION_API_URL || "http://localhost:8003";
const AGENTIC_API_URL = process.env.AGENTIC_API_URL || "http://localhost:8002";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [
      // Agentic Reasoning Service (port 8002) — Ask AI, RAG, Negotiation/Renewals
      // Frontend calls /api/agentic/:path* → maps to /api/v1/:path* on port 8002
      {
        source: "/api/agentic/:path*",
        destination: `${AGENTIC_API_URL}/api/v1/:path*`,
      },
      // Ingestion / Procurement-Core Service (port 8003)
      {
        source: "/api/v1/:path*",
        destination: `${INGESTION_API_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
