import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const devHttps = process.env.VITE_DEV_HTTPS === "1";

export default defineConfig({
  plugins: [react(), ...(devHttps ? [basicSsl()] : [])],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
