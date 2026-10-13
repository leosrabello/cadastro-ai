import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tauri expects a fixed port in development and a relative base in production builds.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: { target: "es2022", sourcemap: false },
});
