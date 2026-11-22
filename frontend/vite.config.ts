import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const apiProxy = {
  "/api": { target: process.env.SMARTDOC_API_ORIGIN ?? "http://127.0.0.1:8000" },
}

export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
