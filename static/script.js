"use strict";

const button = document.getElementById("generate-button");
const status = document.getElementById("status");
const errorMessage = document.getElementById("error");
const payloadRegion = document.getElementById("payload-region");

function setStatus(message, state) {
  status.textContent = message;
  status.dataset.state = state;
}

button.addEventListener("click", async () => {
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "Request in progress…";
  payloadRegion.setAttribute("aria-busy", "true");
  errorMessage.hidden = true;
  setStatus("Requesting…", "loading");

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 10000);
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/v1/compliments/random", {
      method: "GET", headers: { Accept: "application/json" },
      cache: "no-store", signal: controller.signal,
    });
    const body = await response.text();
    const latency = performance.now() - startedAt;
    if (!response.ok) {
      const trace = response.headers.get("X-Trace-ID");
      throw new Error(`HTTP ${response.status}${trace ? ` · Trace ID: ${trace}` : ""}`);
    }
    const payload = JSON.parse(body);
    if (typeof payload.compliment !== "string" ||
        typeof payload.trace_id !== "string" ||
        typeof payload.timestamp !== "string") {
      throw new Error("The API returned an unexpected response format.");
    }
    // API values are rendered as text, never interpreted as HTML.
    document.getElementById("compliment").textContent = payload.compliment;
    document.getElementById("http-status").textContent =
      `${response.status} ${response.statusText}`.trim();
    document.getElementById("latency").textContent = `${latency.toFixed(1)} ms`;
    document.getElementById("trace-id").textContent = payload.trace_id;
    document.getElementById("timestamp").textContent = payload.timestamp;
    document.getElementById("raw-response").textContent = JSON.stringify(payload, null, 2);
    setStatus("Request successful", "success");
  } catch (error) {
    let message;
    if (error.name === "AbortError") {
      message = "The request timed out after 10 seconds. Try again.";
    } else if (error instanceof SyntaxError) {
      message = "The API returned invalid JSON.";
    } else if (error instanceof TypeError) {
      message = "Unable to reach the API. Check your connection and try again.";
    } else {
      message = error.message || "The request failed. Try again.";
    }
    errorMessage.textContent = message;
    errorMessage.hidden = false;
    setStatus("Request failed", "error");
  } finally {
    window.clearTimeout(timeout);
    button.disabled = false;
    button.textContent = "Generate compliment ↗";
    payloadRegion.setAttribute("aria-busy", "false");
  }
});
