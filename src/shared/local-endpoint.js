const LOCAL_API_PREFIXES = {
  "8083": "/local-api/flow",
  "8084": "/local-api/policy",
  "8085": "/local-api/model",
};

// Keep Word's HTTPS webview on the same origin when calling local services.
// Remote endpoints and already-relative proxy paths remain unchanged.
export function resolveLocalEndpoint(endpoint) {
  if (typeof endpoint !== "string" || !endpoint) return endpoint;

  try {
    const url = new URL(endpoint);
    const prefix = LOCAL_API_PREFIXES[url.port];
    if (
      prefix &&
      (url.protocol === "http:" || url.protocol === "https:") &&
      (url.hostname === "localhost" || url.hostname === "127.0.0.1") &&
      !url.username &&
      !url.password
    ) {
      return prefix + url.pathname + url.search + url.hash;
    }
  } catch (_error) {
    // Relative paths and invalid values are handled by the existing caller.
  }

  return endpoint;
}
