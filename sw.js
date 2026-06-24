self.addEventListener('fetch', (event) => {
  // Do not intercept API requests to prevent POST body corruption
  if (event.request.url.includes('/api/')) {
    return;
  }
  event.respondWith(fetch(event.request));
});
