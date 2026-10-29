/* SkyCast AI Web Push worker. */
self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (err) { data = {}; }
  var title = data.title || "SkyCast Weather Alert";
  var options = {
    body: data.message || "Severe weather alert issued for your tracked location.",
    icon: "/static/icons/logo.svg",
    badge: "/static/icons/logo.svg",
    vibrate: [200, 100, 200],
    data: { url: data.url || "/alerts" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var targetUrl = event.notification.data && event.notification.data.url || "/alerts";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windowClients) {
      for (var i = 0; i < windowClients.length; i += 1) {
        if (windowClients[i].url.indexOf(targetUrl) !== -1 && "focus" in windowClients[i]) {
          return windowClients[i].focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
      return undefined;
    })
  );
});