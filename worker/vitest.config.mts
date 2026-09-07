import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

// Worker tests run inside workerd (the real runtime), against a real local D1 —
// the same engine production uses. That is what makes a cache-key or an
// INSERT OR IGNORE test worth writing: a mock of D1 would happily "pass" a
// broken unique index.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.toml" },
      miniflare: {
        // INGEST_TOKEN is a Wrangler secret in production, so it is absent from
        // wrangler.toml by design. Tests never hardcode the real one: they read
        // whatever `env.INGEST_TOKEN` holds, so a developer's local .dev.vars
        // works without its value ever reaching a test file or an assertion.
        bindings: { INGEST_TOKEN: "test-token" },

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
