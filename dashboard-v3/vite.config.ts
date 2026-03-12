import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/universal_room_automation_panel/",
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
