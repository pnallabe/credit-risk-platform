/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/analytics/:path*",
        destination: `${process.env.ANALYTICS_API_URL || "http://localhost:8003"}/v1/analytics/:path*`,
      },
      {
        source: "/api/agent/:path*",
        destination: `${process.env.AGENT_API_URL || "http://localhost:8082"}/v1/agent/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
