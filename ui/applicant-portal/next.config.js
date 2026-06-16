/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.DECISION_API_URL || "http://localhost:8081"}/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
