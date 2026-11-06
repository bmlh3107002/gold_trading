import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev: đặt GT_PUBLIC_URL=http://localhost:5173 cho backend để cookie/redirect khớp origin này.
    proxy: { "/api": "http://localhost:8000", "/auth": "http://localhost:8080" },
  },
});
