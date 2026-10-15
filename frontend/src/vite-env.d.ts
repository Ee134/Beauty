/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 可选：直接指定后端地址（默认走同源 /api/v1，开发时由 vite 代理）。 */
  readonly VITE_API_BASE?: string;
  /** 可选：Web Push VAPID 公钥；未配置时设置页显示 mock/未启用状态。 */
  readonly VITE_VAPID_PUBLIC_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
