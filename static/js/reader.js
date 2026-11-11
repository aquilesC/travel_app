// Trip reader: chapter menu, entry navigation (j/k), map toggle and the photo viewer.
// Announces the entry being read with a "trip:entry" event that trip-map.js follows.
(function () {
  const story = document.querySelector(".story");
  if (!story) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const behavior = reduceMotion ? "auto" : "smooth";
  document.querySelectorAll(".js-only").forEach((el) => (el.hidden = false));

  const entries = Array.from(story.querySelectorAll(".entry[data-entry]"));
  const chapters = Array.from(story.querySelectorAll(".chapter[data-chapter]"));
  const barHeight = () => (story.querySelector(".story-bar")?.offsetHeight || 0) + 8;

  function scrollToEl(el) {
    const top = el.getBoundingClientRect().top + window.scrollY - barHeight();
    window.scrollTo({ top, behavior });
  }

  // --- Which entry / chapter are we reading? -------------------------------
  let current = null;
  function setCurrent(entry) {
    if (!entry || entry === current) return;
    current?.classList.remove("is-current");
    current = entry;
    entry.classList.add("is-current");
    document.dispatchEvent(new CustomEvent("trip:entry", {
      detail: {
        id: Number(entry.dataset.entry),
        lat: entry.dataset.lat ? Number(entry.dataset.lat) : null,
        lon: entry.dataset.lon ? Number(entry.dataset.lon) : null,
      },
    }));
    const chapter = entry.closest(".chapter");
    const label = story.querySelector(".current-chapter");
    if (label) label.textContent = chapter?.dataset.chapter || "Chapters";
    story.querySelectorAll("[data-chapter-link]").forEach((a) => {
      a.classList.toggle("is-current", chapter && a.getAttribute("href") === `#${chapter.id}`);
    });
  }

  // The entry crossing a line 35% down the viewport is the one being read.
  const observer = new IntersectionObserver((records) => {
    const visible = records.filter((r) => r.isIntersecting).map((r) => r.target);
    if (visible.length) setCurrent(visible[0]);
  }, { rootMargin: "-35% 0px -60% 0px" });
  entries.forEach((e) => observer.observe(e));

  // --- Entry navigation --------------------------------------------------------
  function step(direction) {
    if (!entries.length) return;
    const line = barHeight() + 4;
    let target;
    if (direction > 0) {
      target = entries.find((e) => e.getBoundingClientRect().top > line + 2);
    } else {
      target = [...entries].reverse().find((e) => e.getBoundingClientRect().top < line - 2);
    }
    if (target) scrollToEl(target);
  }
  story.querySelector('[data-nav="next"]')?.addEventListener("click", () => step(1));
  story.querySelector('[data-nav="prev"]')?.addEventListener("click", () => step(-1));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (viewer.open) return;
    if (e.key === "j") step(1);
    if (e.key === "k") step(-1);
  });

  // Chapter menu: close after picking, smooth scroll below the sticky bar.
  story.querySelectorAll("[data-chapter-link], .next-chapter").forEach((a) => {
    a.addEventListener("click", (e) => {
      const target = document.querySelector(a.getAttribute("href"));
      if (!target) return;
      e.preventDefault();
      a.closest("details")?.removeAttribute("open");
      scrollToEl(target);
      history.replaceState(null, "", a.getAttribute("href"));
    });
  });

  // --- Map toggle (mostly for phones) -----------------------------------------
  const toggle = story.querySelector(".map-toggle");
  const reader = document.querySelector(".reader");
  toggle?.addEventListener("click", () => {
    const hidden = reader.classList.toggle("map-hidden");
    toggle.setAttribute("aria-pressed", String(!hidden));
    document.dispatchEvent(new Event("trip:resize"));
  });

  // --- Photo viewer -------------------------------------------------------------
  const viewer = document.querySelector("dialog.viewer");
  const items = Array.from(story.querySelectorAll(".lb-item"));
  let index = 0;

  function caption(item) {
    const entry = document.getElementById(`entry-${item.dataset.entry}`);
    const time = entry?.querySelector("time")?.textContent || "";
    const place = entry?.querySelector(".place")?.textContent.replace("📍", "").trim() || "";
    const chapter = entry?.closest(".chapter")?.dataset.chapter || "";
    return [time, place, chapter].filter(Boolean).join(" · ");
  }

  function show(i) {
    if (!items.length) return;
    index = (i + items.length) % items.length;
    const item = items[index];
    const stage = viewer.querySelector(".viewer-stage");
    stage.querySelectorAll("video").forEach((v) => v.pause());
    stage.replaceChildren();
    let media;
    if (item.dataset.kind === "video") {
      media = document.createElement("video");
      Object.assign(media, { src: item.dataset.src, poster: item.dataset.poster, controls: true, playsInline: true });
    } else {
      media = document.createElement("img");
      media.src = item.dataset.src;
      media.alt = "";
    }
    stage.append(media);
    viewer.querySelector(".viewer-count").textContent = `${index + 1} / ${items.length}`;
    viewer.querySelector(".viewer-meta").textContent = caption(item);
    // Preload the neighbours' photos.
    [index + 1, index - 1].forEach((n) => {
      const next = items[(n + items.length) % items.length];
      if (next.dataset.kind === "photo") new Image().src = next.dataset.src;
    });
  }

  function open(i) {
    if (!viewer || !items.length) return;
    show(i);
    if (!viewer.open) viewer.showModal();
  }

  function close() {
    viewer.querySelectorAll("video").forEach((v) => v.pause());
    viewer.close();
  }

  if (viewer) {
    items.forEach((item, i) => {
      const trigger = item.dataset.kind === "video" ? item.querySelector(".expand") : item;
      trigger?.addEventListener("click", (e) => { e.preventDefault(); open(i); });
    });
    viewer.querySelector(".viewer-close").addEventListener("click", close);
    viewer.querySelector(".viewer-prev").addEventListener("click", () => show(index - 1));
    viewer.querySelector(".viewer-next").addEventListener("click", () => show(index + 1));
    viewer.querySelector(".viewer-goto").addEventListener("click", () => {
      const entry = document.getElementById(`entry-${items[index].dataset.entry}`);
      close();
      if (entry) scrollToEl(entry);
    });
    viewer.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") show(index + 1);
      if (e.key === "ArrowLeft") show(index - 1);
    });
    viewer.addEventListener("click", (e) => { if (e.target === viewer) close(); });
    // Swipe left/right.
    let startX = null;
    viewer.addEventListener("pointerdown", (e) => { startX = e.clientX; });
    viewer.addEventListener("pointerup", (e) => {
      if (startX === null) return;
      const dx = e.clientX - startX;
      startX = null;
      if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
    });
  }

  window.TripReader = {
    openMedia(mediaId) {
      const i = items.findIndex((item) => Number(item.dataset.media) === Number(mediaId));
      if (i >= 0) open(i);
    },
    goToEntry(entryId) {
      const entry = document.getElementById(`entry-${entryId}`);
      if (entry) scrollToEl(entry);
    },
  };
})();
