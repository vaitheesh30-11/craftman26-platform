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
    // Required for `instrumentation.ts`'s `register()` to run on Next.js
    // 14.x (stable-by-default only from 15.0) -- without this flag the
    // hook is silently never invoked, no error, no warning.
    instrumentationHook: true,
  },
};

export default nextConfig;
