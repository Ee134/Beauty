/**
 * 入口：仅在**生产构建**中注册 Service Worker（开发时注册会干扰 vite HMR）。
 * 通知权限永远不在首次加载时请求：用户必须在 /settings 明确点击按钮。
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到 #root 容器，index.html 可能被修改。");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// PWA：只有生产构建才注册 sw.js（缓存静态资源；/api/ 始终走网络，不缓存个人信息）。
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker
      .register("/sw.js")
      .catch((error: unknown) => {
        // 注册失败不阻断应用；在控制台如实报告，不假装已具备推送能力。
        console.warn("Service Worker 注册失败（PWA 离线缓存与通知推送将不可用）：", error);
      });
  });
}
