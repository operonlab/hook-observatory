// Web Push handler for Agent Vista (imported by Workbox-generated SW)

self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || "Agent Vista", {
      body: data.body || "",
      icon: data.icon || "./icons/icon-192.png",
      tag: data.tag,
      data: { url: data.url || "/v2/apps/agent-metrics/" },
      vibrate: data.severity === "critical" ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: data.severity !== "info",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/v2/apps/agent-metrics/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wc) => {
      for (const c of wc) {
        if ("focus" in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});
