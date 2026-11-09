// Trip map: GPX tracks coloured by travel mode, check-in points, and the
// dashed path between check-ins. Data comes from the map.json endpoint.
(function () {
  const el = document.getElementById("trip-map");
  if (!el || !window.maplibregl) return;

  fetch(el.dataset.url, { credentials: "same-origin" })
    .then((r) => r.json())
    .then((data) => {
      if (!data.features.length) {
        el.classList.add("empty");
        el.textContent = "No GPX tracks or locations yet.";
        return;
      }
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

      map.on("load", () => {
        map.addSource("trip", { type: "geojson", data });
        map.addLayer({
          id: "path", type: "line", source: "trip",
          filter: ["==", ["get", "kind"], "path"],
          paint: { "line-color": "#334155", "line-width": 2, "line-dasharray": [2, 2] },
        });
        map.addLayer({
          id: "tracks", type: "line", source: "trip",
          filter: ["==", ["get", "kind"], "track"],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": ["get", "color"], "line-width": 4 },
        });
        map.addLayer({
          id: "entries", type: "circle", source: "trip",
          filter: ["==", ["get", "kind"], "entry"],
          paint: {
            "circle-radius": 7, "circle-color": "#e11d48",
            "circle-stroke-color": "#fff", "circle-stroke-width": 2,
          },
        });

        map.on("click", "entries", (e) => {
          const p = e.features[0].properties;
          const link = document.createElement("a");
          link.href = p.anchor;
          link.textContent = p.title || "Open entry";
          new maplibregl.Popup().setLngLat(e.lngLat).setDOMContent(link).addTo(map);
        });
        map.on("click", "tracks", (e) => {
          const p = e.features[0].properties;
          const text = `${p.name} · ${p.mode_label} · ${p.distance_km} km` +
            (p.uphill_m ? ` · ↑${p.uphill_m} m` : "");
          new maplibregl.Popup().setLngLat(e.lngLat).setText(text).addTo(map);
        });
        for (const layer of ["entries", "tracks"]) {
          map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
        }
        map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
      });
    })
    .catch(() => { el.textContent = "The map could not be loaded."; });
})();
