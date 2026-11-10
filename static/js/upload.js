// Chunked, resumable uploads: Cloudflare rejects requests over 100 MB, so files
// go up in pieces of at most `chunk_size` bytes (50 MB) and are joined server-side.
(function () {
  const box = document.getElementById("uploader");
  if (!box) return;
  const input = box.querySelector("input[type=file]");
  const progress = box.querySelector(".upload-progress");
  const csrf = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || "";

  async function call(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: { "X-CSRFToken": csrf, ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  async function uploadFile(file, row) {
    const start = await call(box.dataset.startUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, size: file.size }),
    });
    if (!start.ok) throw new Error(start.data.error || "Could not start the upload");
    const { id, chunk_size: chunkSize } = start.data;
    let offset = 0;
    let failures = 0;
    while (offset < file.size) {
      const chunk = file.slice(offset, offset + chunkSize);
      let result;
      try {
        result = await call(`/uploads/${id}/chunk/?offset=${offset}`, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: chunk,
        });
      } catch (networkError) {
        result = { ok: false, status: 0, data: {} };
      }
      if (result.ok) {
        offset = result.data.received;
        failures = 0;
      } else if (result.status === 409 && typeof result.data.received === "number") {
        offset = result.data.received; // server tells us where to resume
      } else {
        if (++failures > 5) throw new Error(result.data.error || "Upload failed");
        await new Promise((r) => setTimeout(r, 2000 * failures));
        const status = await call(`/uploads/${id}/`).catch(() => null);
        if (status && status.ok) offset = status.data.received;
      }
      row.textContent = `${file.name}: ${Math.floor((offset / file.size) * 100)}%`;
    }
    const done = await call(`/uploads/${id}/complete/`, { method: "POST" });
    if (!done.ok) throw new Error(done.data.error || "Could not finish the upload");
    return done.data;
  }

  input.addEventListener("change", async () => {
    const files = Array.from(input.files);
    input.disabled = true;
    let failed = false;
    let skipped = false;
    for (const file of files) {
      const row = document.createElement("li");
      row.textContent = `${file.name}: waiting`;
      progress.appendChild(row);
      try {
        const result = await uploadFile(file, row);
        if (result.skipped) {
          skipped = true;
          row.textContent = `${file.name}: skipped (${result.skipped})`;
        } else {
          row.textContent = `${file.name}: uploaded ✓`;
        }
      } catch (error) {
        failed = true;
        row.textContent = `${file.name}: ${error.message}`;
        row.className = "error";
      }
    }
    input.disabled = false;
    input.value = "";
    // Stay on the page when something was skipped or failed, so it can be read.
    if (!failed && !skipped) {
      if (box.dataset.doneUrl) window.location.href = box.dataset.doneUrl;
      else window.location.reload();
    }
  });

  // While anything is processing, refresh the list when it's done.
  const list = document.getElementById("media-list");
  if (list && list.querySelector('[data-status="pending"]')) {
    const timer = setInterval(async () => {
      const result = await call(list.dataset.statusUrl).catch(() => null);
      if (result && result.ok && !result.data.media.some((m) => m.status === "pending")) {
        clearInterval(timer);
        window.location.reload();
      }
    }, 5000);
  }
})();
