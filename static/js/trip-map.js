// Trip map: GPX tracks by travel mode, check-ins and the path between them, every
// located photo (clustered dots), and thumbnails for the entry being read. Follows
// the "trip:entry" events from reader.js; clicks open the photo viewer / the entry.
(function () {
  const el = document.getElementById("trip-map");
  if (!el || !window.maplibregl) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let pendingEntry = null;
  document.addEventListener("trip:entry", (e) => { pendingEntry = e.detail; });

  fetch(el.dataset.url, { credentials: "same-origin" })
    .then((r) => r.json())
    .then((data) => {
      if (!data.features.length && !el.dataset.liveUrl) {
        el.classList.add("empty");
        el.textContent = "No GPX tracks or locations yet.";
        return;
      }
      const photos = data.features.filter((f) => f.properties.kind === "photo");
      const story = { type: "FeatureCollection", features: data.features.filter((f) => f.properties.kind !== "photo") };

      const map = new maplibregl.Map({
        container: el,
        style: "https://tiles.openfreemap.org/styles/liberty",
        attributionControl: { compact: true },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }));

      const bounds = new maplibregl.LngLatBounds();
      for (const f of data.features) {
        const g = f.geometry;
        const coords = g.type === "Point" ? [g.coordinates]
          : g.type === "LineString" ? g.coordinates : g.coordinates.flat();
        coords.forEach((c) => bounds.extend(c));
      }

      let thumbs = [];
      function showEntry(detail) {
        thumbs.forEach((m) => m.remove());
        thumbs = photos.filter((f) => f.properties.entry_id === detail.id).slice(0, 12).map((f) => {
          const img = document.createElement("img");
          img.src = f.properties.thumb;
          img.alt = "";
          img.className = "map-thumb";
          img.addEventListener("click", (e) => {
            e.stopPropagation();
            window.TripReader?.openMedia(f.properties.media_id);
          });
          return new maplibregl.Marker({ element: img }).setLngLat(f.geometry.coordinates).addTo(map);
        });
        if (map.getLayer("entry-current")) {
          map.setFilter("entry-current", ["all", ["==", ["get", "kind"], "entry"], ["==", ["get", "entry_id"], detail.id]]);
        }
        if (detail.lat === null) return;
        const target = { center: [detail.lon, detail.lat], zoom: Math.max(map.getZoom(), 11) };
        if (reduceMotion) map.jumpTo(target);
        else map.flyTo({ ...target, speed: 1.4, curve: 1.3, essential: false });
      }

      map.on("load", () => {
        map.addSource("trip", { type: "geojson", data: story });
        map.addSource("photos", {
          type: "geojson", cluster: true, clusterRadius: 36, clusterMaxZoom: 15,
          data: { type: "FeatureCollection", features: photos },
        });
        map.addLayer({
          id: "path", type: "line", source: "trip", filter: ["==", ["get", "kind"], "path"],
          paint: { "line-color": "#334155", "line-width": 2, "line-dasharray": [2, 2] },
        });
        map.addLayer({
          // Paths recorded by the iPhone app, one per traveller (members' map only).
          id: "recorded", type: "line", source: "trip", filter: ["==", ["get", "kind"], "recorded"],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": "#0e7490", "line-width": 3, "line-opacity": 0.75 },
        });
        map.addLayer({
          id: "tracks", type: "line", source: "trip", filter: ["==", ["get", "kind"], "track"],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": ["get", "color"], "line-width": 4 },
        });
        map.addLayer({
          id: "photo-clusters", type: "circle", source: "photos", filter: ["has", "point_count"],
          paint: {
            "circle-color": "#0f766e", "circle-opacity": 0.85,
            "circle-radius": ["step", ["get", "point_count"], 13, 10, 17, 50, 22],
            "circle-stroke-color": "#fff", "circle-stroke-width": 2,
          },
        });
        map.addLayer({
          id: "photo-cluster-count", type: "symbol", source: "photos", filter: ["has", "point_count"],
          layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12,
                    "text-font": ["Noto Sans Regular"] },
          paint: { "text-color": "#fff" },
        });
        map.addLayer({
          id: "photo-dots", type: "circle", source: "photos", filter: ["!", ["has", "point_count"]],
          paint: { "circle-radius": 5, "circle-color": "#0f766e", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 },
        });
        map.addLayer({
          id: "entries", type: "circle", source: "trip", filter: ["==", ["get", "kind"], "entry"],
          paint: { "circle-radius": 7, "circle-color": "#e11d48", "circle-stroke-color": "#fff", "circle-stroke-width": 2 },
        });
        map.addLayer({
          id: "entry-current", type: "circle", source: "trip", filter: ["==", ["get", "entry_id"], -1],
          paint: { "circle-radius": 13, "circle-color": "rgba(225,29,72,0.18)", "circle-stroke-color": "#e11d48", "circle-stroke-width": 2 },
        });

        map.on("click", "entries", (e) => window.TripReader?.goToEntry(e.features[0].properties.entry_id));
        map.on("click", "photo-dots", (e) => window.TripReader?.openMedia(e.features[0].properties.media_id));
        map.on("click", "photo-clusters", async (e) => {
          const feature = e.features[0];
          const zoom = await map.getSource("photos").getClusterExpansionZoom(feature.properties.cluster_id);
          map.easeTo({ center: feature.geometry.coordinates, zoom, duration: reduceMotion ? 0 : 500 });
        });
        map.on("click", "tracks", (e) => {
          const p = e.features[0].properties;
          const text = `${p.name} · ${p.mode_label} · ${p.distance_km} km` + (p.uphill_m ? ` · ↑${p.uphill_m} m` : "");
          new maplibregl.Popup().setLngLat(e.lngLat).setText(text).addTo(map);
        });
        for (const layer of ["entries", "tracks", "photo-dots", "photo-clusters"]) {
          map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
        }
        if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
        if (el.dataset.liveUrl) startLive(map, el.dataset.liveUrl, bounds.isEmpty());

        document.addEventListener("trip:entry", (e) => showEntry(e.detail));
        if (pendingEntry) showEntry(pendingEntry);
      });
      document.addEventListener("trip:resize", () => setTimeout(() => map.resize(), 50));
    })
    .catch(() => { el.textContent = "The map could not be loaded."; });

  // Live location (v4 #27): latest position + today's path per traveller, refreshed every
  // minute while the tab is visible. Share-link viewers get delayed, rounded data.
  function startLive(map, url, fitToLive) {
    const empty = { type: "FeatureCollection", features: [] };
    map.addSource("live", { type: "geojson", data: empty });
    map.addLayer({
      id: "live-path", type: "line", source: "live", filter: ["==", ["geometry-type"], "LineString"],
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#0891b2", "line-width": 3 },
    });
    map.addLayer({
      id: "live-halo", type: "circle", source: "live", filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 16, "circle-color": "rgba(8,145,178,0.25)" },
    });
    map.addLayer({
      id: "live-dot", type: "circle", source: "live", filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 7, "circle-color": "#0891b2", "circle-stroke-color": "#fff", "circle-stroke-width": 2 },
    });
    const badge = document.createElement("div");
    badge.className = "live-badge";
    badge.hidden = true;
    el.appendChild(badge);

    let timer = null;
    let fitted = !fitToLive;
    function ago(iso) {
      const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
      if (minutes < 1) return "just now";
      if (minutes < 60) return `${minutes} min ago`;
      const hours = Math.round(minutes / 60);
      return `${hours} h ago`;
    }
    async function refresh() {
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        if (!response.ok) return;
        const data = await response.json();
        const features = [];
        const parts = [];
        for (const t of data.travellers) {
          if (t.path.length > 1) features.push({ type: "Feature", geometry: { type: "LineString", coordinates: t.path }, properties: { name: t.name } });
          features.push({ type: "Feature", geometry: { type: "Point", coordinates: [t.latest.longitude, t.latest.latitude] }, properties: { name: t.name } });
          parts.push(`${t.name}: ${ago(t.latest.recorded_at)}`);
        }
        map.getSource("live").setData({ type: "FeatureCollection", features });
        badge.hidden = !parts.length;
        badge.textContent = parts.length ? `Live · ${parts.join(" · ")}` + (data.delay_minutes ? ` (shown ${data.delay_minutes} min later)` : "") : "";
        if (!fitted && features.length) {
          const b = new maplibregl.LngLatBounds();
          features.forEach((f) => (f.geometry.type === "Point" ? [f.geometry.coordinates] : f.geometry.coordinates).forEach((c) => b.extend(c)));
          map.fitBounds(b, { padding: 60, maxZoom: 13, duration: 0 });
          fitted = true;
        }
      } catch (_) { /* offline: try again next time */ }
    }
    function schedule() {
      clearInterval(timer);
      timer = null;
      if (document.visibilityState === "visible") {
        refresh();
        timer = setInterval(refresh, 60000);
      }
    }
    document.addEventListener("visibilitychange", schedule);
    schedule();
  }
})();
