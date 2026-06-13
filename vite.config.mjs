import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "src/ui/frontend",
  publicDir: false,
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/resources": "http://127.0.0.1:8765",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  build: {
    outDir: "../../../dist/frontend",
    emptyOutDir: true,
  },
});
