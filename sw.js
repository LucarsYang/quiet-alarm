/* 安靜警報 service worker：先走網路（拿到最新版），斷網就用快取。改了靜態檔清單就改 VERSION。 */
var VERSION = 'quiet-alarm-v1';
var FILES = [
  './',
  'index.html',
  'style.css',
  'logic.js',
  'app.js',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'sounds/please-quiet.m4a',
];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) { return c.addAll(FILES); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  // 音檔可能帶 Range，直接用快取整檔回（iOS 播 m4a 會送 Range）
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && res.status === 200 && !req.headers.has('range')) {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req, { ignoreSearch: true }).then(function (hit) {
        return hit || (req.mode === 'navigate' ? caches.match('index.html') : Response.error());
      });
    })
  );
});
