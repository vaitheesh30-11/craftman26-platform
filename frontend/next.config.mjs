/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // The BFF proxy (`app/api/proxy/[...path]/route.ts`) requires a live
  // Node.js server for streaming + HttpOnly cookie handling, so `output:
  // "export"` (pure static) is not viable — `standalone` still produces
  // the deployable static asset tree phase-00 §8 asks for (Amplify
  // Hosting/CloudFront can serve `.next/static` + `public/` directly)
  // while keeping the Node runtime for the proxy and auth routes.
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
