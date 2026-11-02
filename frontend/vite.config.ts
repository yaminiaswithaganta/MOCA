import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const SERVER = "http://127.0.0.1:8000";

// `npm run dev` serves the app with live reload and passes API calls to the Python server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": SERVER,
      "/images": SERVER,
      "/ws": { target: SERVER, ws: true },
    },
  },
});
