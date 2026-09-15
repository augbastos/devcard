import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

// Worker tests run inside workerd (the real runtime), against a real local D1 —
// the same engine production uses. That is what makes a cache-key or an
// INSERT OR IGNORE test worth writing: a mock of D1 would happily "pass" a
// broken unique index.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.example.jsonc" },
      miniflare: {
        // Fixed values, so the suite never depends on a real deployment:
        // INGEST_TOKEN is a Wrangler secret in production and absent from the
        // config by design; the template's vars are placeholders; and a local
        // `.dev.vars` must not change what a test sees. TIMEZONE is far enough
        // from UTC that a day key computed in UTC fails the tests that pin it.
        bindings: {
          INGEST_TOKEN: "test-token",
          GITHUB_USERNAME: "devcard-test",
          TIMEZONE: "Asia/Tokyo",
        },

        // The card enriches itself from github.com (avatar, sponsors, stars).
        // Every outbound request is answered here instead, so the suite never
        // depends on the network or on the real account's live numbers.
        // Anything unexpected comes back 599 — visible, not silently live.
        outboundService(request: Request): Response {
          const url = new URL(request.url);
          if (url.hostname === "github.com" && /^\/[^/]+\.png$/.test(url.pathname)) {
            return new Response("PNGDATA", { headers: { "Content-Type": "image/png" } });
          }
          if (url.hostname === "github.com" && url.pathname.startsWith("/sponsors/")) {
            return new Response(null, { status: 404 });
          }
          if (url.hostname === "api.github.com" && url.pathname.startsWith("/repos/")) {
            return Response.json({ stargazers_count: 7 });
          }
          return new Response(`unmocked outbound request: ${request.url}`, { status: 599 });
        },
      },
    }),
  ],
  test: {
    // A cold render fans out to several cached subrequests; the 5s default is
    // tight on a cold workerd start under CI.
    testTimeout: 15000,
  },
});
