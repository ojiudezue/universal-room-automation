import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/universal_room_automation_panel/",
  build: {
    outDir: "../custom_components/universal_room_automation/frontend",
    emptyOutDir: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom"],
          hakit: ["@hakit/core"],
        },
      },
    },
  },
  // Only include English locale from date-fns (HAKit dependency)
  resolve: {
    alias: [
      // Redirect all date-fns locale imports to English
      {
        find: /^date-fns\/locale\/(?!en\b).*/,
        replacement: "date-fns/locale/en-US",
      },
    ],
  },
});
