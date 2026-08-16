import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
);

// Requests cancelled by a page navigation (analytics beacons, in-flight GETs) reject with
// "Failed to fetch". They are harmless, so keep them from surfacing as app errors.
let unloading = false;
["pagehide", "beforeunload"].forEach((e) => window.addEventListener(e, () => { unloading = true; }));
window.addEventListener("unhandledrejection", (event) => {
  const message = String(event.reason?.message || event.reason || "");
  const isAbort = /Failed to fetch|NetworkError|load failed|aborted/i.test(message);
  if (isAbort && (unloading || document.visibilityState === "hidden")) event.preventDefault();
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
