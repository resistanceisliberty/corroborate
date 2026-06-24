// Corroborate frontend (M5). Markers colored by calibrated P(real); size by
// independent sources; click for the corroborating sources + refutation flag.
// A time slider replays events as they would have arrived (filter by est_time).

const map = new maplibregl.Map({
  container: "map",
  style: "https://demotiles.maplibre.org/style.json",
  center: [0, 20],
  zoom: 1.3,
});

let allFeatures = [];
let times = [];
let maxScore = 0.0001;

// Low score -> red (uncertain), high -> green (confident). Domain scaled to the
// data's max because calibrated scores can sit in a narrow, low range.
function colorExpr() {
  return [
    "interpolate", ["linear"], ["coalesce", ["get", "score"], 0],
    0, "#d73027",
    maxScore * 0.5, "#fee08b",
    maxScore, "#1a9850",
  ];
}

function visibleData(upToMs) {
  const feats = allFeatures.filter((f) => {
    const t = Date.parse(f.properties.est_time);
    return isNaN(t) || t <= upToMs;
  });
  document.getElementById("count").textContent = `${feats.length} / ${allFeatures.length} events`;
  return { type: "FeatureCollection", features: feats };
}

function wireSlider() {
  const slider = document.getElementById("time");
  const label = document.getElementById("time-label");
  if (!times.length) return;
  const minT = times[0], maxT = times[times.length - 1];
  const update = () => {
    const frac = slider.value / 100;
    const upTo = minT + frac * (maxT - minT);
    label.textContent = new Date(upTo).toISOString().replace("T", " ").slice(0, 16) + "Z";
    map.getSource("events").setData(visibleData(upTo));
  };
  slider.addEventListener("input", update);
  update();
}

async function updateStatus() {
  const ts = allFeatures.map((f) => Date.parse(f.properties.est_time)).filter((t) => !isNaN(t));
  if (ts.length) {
    const age = Math.round((Date.now() - Math.max(...ts)) / 60000);
    document.getElementById("freshness").textContent = `newest event: ${age} min ago`;
  }
  const status = await fetch("/status.json").then((r) => r.json()).catch(() => null);
  if (!status) return;
  const box = document.getElementById("sources");
  box.innerHTML = "";
  for (const s of status.sources) {
    const last = s.last_success ? Date.parse(s.last_success) : NaN;
    const age = isNaN(last) ? Infinity : Math.round((Date.now() - last) / 60000);
    const stale = s.ok === false || age > 30;
    const chip = document.createElement("span");
    chip.className = "chip " + (stale ? "stale" : "ok");
    chip.textContent = isNaN(last) ? `${s.source_id} ✕` : `${s.source_id} ${age}m`;
    chip.title = s.last_error || (s.last_success ? `last ok: ${s.last_success}` : "no successful poll");
    box.appendChild(chip);
  }
}

map.on("load", async () => {
  const fc = await fetch("/events.geojson")
    .then((r) => r.json())
    .catch(() => ({ type: "FeatureCollection", features: [] }));

  allFeatures = fc.features;
  maxScore = Math.max(0.0001, ...allFeatures.map((f) => f.properties.score || 0));
  times = allFeatures
    .map((f) => Date.parse(f.properties.est_time))
    .filter((t) => !isNaN(t))
    .sort((a, b) => a - b);

  map.addSource("events", { type: "geojson", data: visibleData(Infinity) });
  map.addLayer({
    id: "events",
    type: "circle",
    source: "events",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "n_independent"], 1], 1, 4, 12, 16],
      "circle-color": colorExpr(),
      "circle-opacity": 0.85,
      "circle-stroke-width": ["case", ["get", "refutation_flag"], 3, 1],
      "circle-stroke-color": ["case", ["get", "refutation_flag"], "#7b3294", "#333"],
    },
  });

  map.on("click", "events", (e) => {
    const p = e.features[0].properties;
    let sources = p.sources;
    try { sources = JSON.parse(p.sources); } catch (_) { /* already a string */ }
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>P(real): ${(+p.score || 0).toFixed(3)}</strong><br/>` +
        `magnitude: ${p.max_magnitude ?? "—"}<br/>` +
        `independent sources: ${p.n_independent} (of ${p.n_claims} claims)<br/>` +
        `sources: ${Array.isArray(sources) ? sources.join(", ") : sources}<br/>` +
        `<span class="muted">${p.est_time || ""}</span>` +
        (p.refutation_flag ? `<br/><em style="color:#7b3294">⚠ sources disagree</em>` : "")
      )
      .addTo(map);
  });
  map.on("mouseenter", "events", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "events", () => (map.getCanvas().style.cursor = ""));

  wireSlider();
  updateStatus();
});
