import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // v5.0: base path MUST match the panel URL registered in __init__.py:2171
  // (`panel_v3_url = f"/{DOMAIN}_panel_v3"`). Mismatch breaks asset loading.
  base: "/universal_room_automation_panel_v3/",
  build: {
    outDir: "../custom_components/universal_room_automation/frontend-v3",
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Vendor / hakit / charts split keeps the top-of-fold cacheable.
        // date-fns locale shards remain lazy-loaded (~60 small chunks);
        // resolve.alias below redirects all non-en imports to en-US so the
        // shards are only built once even if hakit's UI internals appear
        // to use multiple locales. The dashboard never eagerly downloads
        // them — they're chunked by Rollup's default dynamic-import split.
        manualChunks: {
          vendor: ["react", "react-dom"],
          hakit: ["@hakit/core"],
          charts: ["recharts"],
        },
      },
    },
  },
  resolve: {
    // Belt-and-suspenders: alias still redirects non-en locale paths to en-US
    // for the cases where the import is a plain string. The manualChunks
    // function above catches the rest (dynamic imports + transitive deps).
    alias: [
      {
        find: /^date-fns\/locale\/(?!en\b).*/,
        replacement: "date-fns/locale/en-US",
      },
    ],
  },
});
