/**
 * BeautyCare 演示 PWA Service Worker。
 *
 * 策略：
 * - 静态资源：cache-first，缓存名带版本号（升级 version 即失效旧缓存）。
 * - /api/：network-only，个人 API 响应绝不写入缓存（spec 第 22 节）。
 * - push：显示中性通知（标题/正文不含症状、订单号、完整行程等敏感内容）。
 * - notificationclick：聚焦已打开窗口或打开 data.url 深链接。
 *
 * 说明：本 SW 不承担常驻天气轮询；离线时不会确认计划或提交工单。
 */

const CACHE_VERSION = "beautycare-static-v1";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  // 个人 API 响应：只用网络，永不缓存。
  if (isApiRequest(url)) {
    event.respondWith(fetch(request));
    return;
  }
  // 静态资源：cache-first，回退网络并写入缓存。
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(request)
        .then((response) => {
          if (response.ok && response.type === "basic") {
            const clone = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match("/index.html"));
    }),
  );
});

// 推送：只显示中性文案；敏感内容（症状、订单号、完整行程）不进入锁屏摘要。
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const title = data.title || "美妆管家有新的服务提醒";
  const body = data.body || "打开应用查看详情（本地演示环境，未接入真实推送服务）。";
  const url = (data.data && data.data.url) || data.url || "/inbox";
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url },
      tag: data.tag || "beautycare-service",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/inbox";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          client.focus();
          if ("navigate" in client) {
            return client.navigate(target);
          }
          return undefined;
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(target);
      }
      return undefined;
    }),
  );
});
