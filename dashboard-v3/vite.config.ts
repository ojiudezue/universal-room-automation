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
        manualChunks: {
          vendor: ["react", "react-dom"],
          hakit: ["@hakit/core"],
          charts: ["recharts"],
        },
      },
    },
  },
  resolve: {
    alias: [
      {
        find: /^date-fns\/locale\/(?!en\b).*/,
        replacement: "date-fns/locale/en-US",
      },
    ],
  },
});
