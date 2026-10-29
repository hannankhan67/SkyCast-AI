/* SkyCast AI Web Push registration and subscription persistence. */
(function () {
  "use strict";

  function urlBase64ToUint8Array(value) {
    var padding = "=".repeat((4 - value.length % 4) % 4);
    var base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = window.atob(base64);
    return Uint8Array.from(Array.prototype.map.call(raw, function (char) {
      return char.charCodeAt(0);
    }));
  }

  window.initPushSubscription = function () {
    var publicKey = window.SKYCAST_VAPID_PUBLIC_KEY;
    if (!publicKey || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return Promise.resolve({ permission: "unsupported" });
    }
    return navigator.serviceWorker.register("/static/sw.js").then(function (registration) {
      return Notification.requestPermission().then(function (permission) {
        if (permission !== "granted") return { permission: permission };
        return registration.pushManager.getSubscription().then(function (subscription) {
          if (subscription) return subscription;
          return registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey)
          });
        }).then(function (subscription) {
          return fetch("/api/notifications/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(subscription)
          }).then(function (response) {
            if (!response.ok) throw new Error("Push subscription was not saved");
            return { permission: permission };
          });
        });
      });
    }).catch(function (error) {
      console.error("Push registration failed:", error);
      return { permission: "error" };
    });
  };

  if ("serviceWorker" in navigator && window.SKYCAST_VAPID_PUBLIC_KEY) {
    navigator.serviceWorker.register("/static/sw.js").catch(function () {});
  }
}());