(() => {
  let inFlight = false;
  async function beat() {
    if (document.visibilityState !== "visible" || inFlight) return;
    inFlight = true;
    try {
      await fetch("/api/web-presence", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: "{}",
        signal: AbortSignal.timeout(5000), cache: "no-store"
      });
    } catch (_) {
      // Next heartbeat retries automatically.
    } finally {
      inFlight = false;
    }
  }
  document.addEventListener("visibilitychange", beat);
  setInterval(beat, 8000);
  beat();
})();
