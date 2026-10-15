import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * BeautyCare 演示前端构建配置。
 * - 构建产物输出到 dist/，部署在域名根路径。
 * - 开发服务器把 /api 代理到本地 FastAPI（127.0.0.1:8000），
 *   因此 `pnpm dev` 可以直接对着本地后端联调，无需配置 CORS 密钥。
 */
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    // 与 dev 相同的代理：让 `pnpm preview` 也能直接对着本地后端验证构建产物。
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
