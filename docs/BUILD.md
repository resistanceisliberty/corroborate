# Corroborate — Build Document

An automated, calibrated, **independence-aware** event corroboration scorer.

Given many noisy claims that "something happened somewhere at some time," it
associates them in space-time, collapses sources that aren't really independent,
and emits a **calibrated `P(real)`** per candidate event — plus a refutation flag
when sources disagree.

The prototype calibrates on **earthquakes**, because USGS gives free, exact ground
truth to check the score against. Once the engine is calibrated, it ports to domains with no clean ground truth (conflict, disaster).

---

## 1. What this project brings to the table

1. **Continuous, calibrated score** — not a binary verified/unverified stamp.
   "Score 0.8" should mean ~80% of such events are real (provable via a
   reliability diagram against USGS).
2. **Source-independence weighting** — 12 outlets reposting one wire ≈ 1 source,
   not 12.
3. **Refutation signal** — surface contradictions (claims splitting into two
   incompatible locations/times) are flagged instead of averaged away.
4. **Cross-modal corroboration (phase 2)** — does a social claim line up with an
   independent seismic network, a satellite hit, an ADS-B track?

Baseline to beat / read first: [**EventMapper**](https://arxiv.org/pdf/2001.08700) —
"Detecting Real-World Physical Events Using Corroborative and Probabilistic
Sources." It uses a spatio-temporal grid to score corroboration; I extend it
with independence weighting, calibration, and refutation.

---

## 2. Data sources (earthquakes, all free)

### Ground truth (authoritative label set)
- **USGS real-time GeoJSON feeds** — no API key.
  - `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson`
  - `.../all_day.geojson`, `.../2.5_day.geojson`, `.../significant_month.geojson`
  - Feature `properties`: `mag, place, time` (epoch ms UTC), `updated, felt, cdi,
    mmi, alert, tsunami, sig, net, code, ids, sources, types, magType, type, title`.
  - Geometry: `[lon, lat, depth_km]`.

### Probabilistic pool (what we actually score)
- **EMSC** (European-Mediterranean Seismological Centre) — an *independent*
  authoritative network. Real-time feed + "LastQuake" crowdsourced felt reports.
  - FDSN event service: `https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=...`
  - Independence from USGS is the cleanest demonstration of source weighting.
- **Mastodon** — *unauthenticated* public hashtag timeline
  (`/api/v1/timelines/tag/{tag}`), so it's the social source that runs live out of
  the box. HTML content is stripped, then geoparsed.
- **Bluesky** — `app.bsky.feed.searchPosts`. The public AppView now requires auth,
  so this is credential-gated: set `BLUESKY_IDENTIFIER` + `BLUESKY_APP_PASSWORD`
  (an app password). Creates a PDS session, then searches the same keyword set.
- **X.com (formerly Twitter)** — recent-search endpoint, same keyword set. Highest
  volume but the costliest and least open social source:
  - API v2 `GET /2/tweets/search/recent` (Bearer token; **paid tier** — recent
    search needs at least Basic, and `geo`/place expansions need elevated access).
  - Pull `geo.coordinates` / `geo.place_id` where present; otherwise hand the post
    text to `geoparse.py` like any other social claim.
  - Heaviest dedup load: retweets/quote-posts of one wire are prototypical case
    for independence weighting, so X is where §4.3 earns its keep.
- **Reddit** — `search` over public posts, same keyword set. Application-only
  OAuth (`REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET`); discussion-heavy and weakly
  geolocated, so it leans on `geoparse.py`.
- **News / disaster RSS** — GDACS (`https://www.gdacs.org/xml/rss.xml`); we keep
  its earthquake items (georss coords + magnitude parsed from the severity field).

> Note on independence: USGS held out as ground-truth labels. EMSC + social +
> news form the probabilistic pool we cluster and score. EMSC is a reliable
> single source; social is many weakly-independent sources where dedup matters.

---

## 3. Data model (DuckDB + spatial extension)

Embedded, no server, fast spatial joins, plays well with `uv`.

```sql
-- Every input normalizes to a Claim.
CREATE TABLE claims (
  claim_id          UUID PRIMARY KEY,
  source_id         TEXT,           -- 'usgs' | 'emsc' | 'bluesky' | 'x' | 'rss:gdacs'
  source_type       TEXT,           -- 'seismic_network' | 'social' | 'news'
  external_id       TEXT,           -- network's own id (exact-dup key)
  ingested_at       TIMESTAMP,
  event_time        TIMESTAMP,      -- UTC, claimed time of event
  time_uncertainty_s DOUBLE,
  lat               DOUBLE,
  lon               DOUBLE,
  loc_uncertainty_km DOUBLE,
  magnitude         DOUBLE,         -- nullable
  raw_text          TEXT,
  raw_json          JSON
);

-- Candidate events = clusters of claims.
CREATE TABLE events (
  event_id          UUID PRIMARY KEY,
  centroid_lat      DOUBLE,
  centroid_lon      DOUBLE,
  est_time          TIMESTAMP,
  first_seen        TIMESTAMP,
  last_updated      TIMESTAMP,
  n_claims          INTEGER,
  n_independent     DOUBLE,         -- effective independent sources
  n_source_types    INTEGER,
  score             DOUBLE,         -- calibrated P(real)
  refutation_flag   BOOLEAN,
  status            TEXT            -- 'candidate' | 'scored'
);

CREATE TABLE event_claims (
  event_id          UUID,
  claim_id          UUID,
  weight            DOUBLE          -- independence weight in [0,1]
);

-- USGS ground truth catalog (labels for calibration).
CREATE TABLE ground_truth (
  gt_id             TEXT PRIMARY KEY,  -- USGS id
  event_time        TIMESTAMP,
  lat               DOUBLE,
  lon               DOUBLE,
  magnitude         DOUBLE,
  raw_json          JSON
);

-- Per-source ingest health (map freshness indicator + failure visibility).
CREATE TABLE source_health (
  source_id         TEXT PRIMARY KEY,
  updated_at        TIMESTAMP,
  ok                BOOLEAN,
  n_claims          INTEGER,
  last_success      TIMESTAMP,
  last_error        TEXT
);
```

---

## 4. Pipeline

```
ingest/* ──> claims ──> dedup ──> cluster (ST-DBSCAN) ──> events
                                                            │
                          ground_truth (USGS) ──> label ────┤
                                                            ▼
                                              feature extraction
                                                            │
                                                            ▼
                                           calibrated scorer -> P(real)
                                                            │
                                                            ▼
                                          FastAPI GeoJSON -> MapLibre map
```

### 4.1 Ingest (`src/corroborate/ingest/`)
Async pollers, one per source, all emit normalized `Claim`s. Base class handles
polling cadence, dedup-on-write by `external_id`, and writing `raw_json`.

### 4.2 Geoparse (`geoparse.py`)
USGS/EMSC arrive geocoded. Social/news need extraction: an offline gazetteer
(`geonamescache` — cities + country capitals) plus a small supplement of
sub-national seismic regions and country demonyms (`Japanese`, `Chilean`), with a
proper-noun heuristic and a confidence floor
that drops claims with no confident match → centroid + `loc_uncertainty_km`
(bigger for country-level, smaller for a named town). This is the messiest part;
budget time.

### 4.3 Dedup / independence (`dedup.py`) — what sets this apart
- **Exact dup:** same `external_id` → drop.
- **Near dup:** MinHash (datasketch) over shingled text; Jaccard > 0.8 groups
  reposts/quote-tweets of the same wire.
- **Independence weight:** each near-dup group contributes total weight ~1, split
  across its members (`w_i = 1 / group_size`). Same `source_id` posting repeatedly
  is further down-weighted. Effective independent sources:
  `n_independent = Σ over distinct near-dup groups of (distinct origin? 1 : <1)`.

### 4.4 Cluster / spatio-temporal matching (`cluster.py`)
ST-DBSCAN over claims with a combined metric: haversine distance + scaled time
difference. Defaults (configurable): `eps_space = 100 km`, `eps_time = 30 min`,
`min_samples = 2`. Each cluster becomes a candidate `event`.

For continuous operation `run_cluster` only clusters a rolling
`CLUSTER_WINDOW_HOURS` window of claims (anchored on the most recent claim, so it
behaves the same live or on a replayed dump) — clustering is O(n²), so a full
recompute over all history would eventually OOM. It rebuilds the events inside the
window, leaves older events untouched, and prunes claims/events/ground-truth past
`CLAIM_RETENTION_HOURS`.

### 4.5 Score (`score.py`)
Per-cluster feature vector:
- `n_independent` — effective independent sources (post-dedup)
- `n_source_types` — cross-modal diversity
- `spatial_dispersion_km` — weighted std of claim coords
- `temporal_spread_s` — spread of claimed times
- `consolidation_lag_s` — earliest claim → cluster reaching `min_samples`
- `max_source_prior` — best per-source reliability prior
- `max_magnitude` — strongest reported magnitude in the cluster

Model: `LogisticRegression` wrapped in `CalibratedClassifierCV` (isotonic) so
the output is an honest probability.

`scripts/score_events.py` writes calibrated `P(real)` to the current events using
the *saved* model, so the live loop can re-score each clustering pass cheaply
without the heavier retrain in `train.py` (which only needs to run occasionally).

### 4.6 Calibrate / validate (`calibrate.py`)
Label each candidate by whether a USGS event exists within `Δd ≤ 150 km`,
`Δt ≤ 1 h`. Train/test split by time. Report:
- **Reliability diagram** (the money plot — is 0.8 really ~80%?)
- **Brier score**, **PR-AUC**, confusion at chosen threshold.

### 4.7 Refutation (`cluster.py` / `score.py`)
If a candidate's claims split into ≥2 spatial subclusters separated by
> `refute_dist` with comparable mass (or incompatible times), set
`refutation_flag = true` and expose both interpretations rather than averaging.

### 4.8 Serve (`api.py`) + map (`web/`)
FastAPI → scored events as GeoJSON (`/events.geojson?since=...`). MapLibre GL +
a global basemap (`demotiles.maplibre.org`): markers colored by `P(real)`; click → sources,
the space-time proof, and refutation flag; time slider replays score as reports
arrive.

Each ingest writes per-source outcomes to `source_health`; `/status.json` exposes
them and the map shows a freshness line (age of the newest event) plus a chip per
source that turns red when a feed has failed or gone stale — passive failure
alerting with no mail server. (Push alerting — email/webhook — is a later add.)

---

## 5. File layout

```
corroborate/
  pyproject.toml
  README.md
  .gitignore
  docs/BUILD.md            <- this file
  src/corroborate/
    __init__.py
    config.py              # tunables (eps_space, windows, thresholds)
    db.py                  # duckdb conn + schema init
    models.py              # Claim / Event dataclasses
    ingest/
      __init__.py
      base.py              # Poller base class
      usgs.py              # ground truth
      emsc.py              # independent network
      mastodon.py          # social — public tag timeline (no auth)
      bluesky.py           # social — app password
      x.py                 # social — X.com / Twitter (paid API)
      reddit.py            # social — application-only OAuth
      rss.py               # news/disaster — GDACS
    geoparse.py
    dedup.py
    cluster.py
    score.py
    calibrate.py
    api.py
  web/
    index.html             # MapLibre GL
    app.js
  scripts/
    run_ingest.py
    run_cluster.py         # windowed cluster + retention prune
    train.py
    score_events.py        # re-score events from the saved model
    run_cycle.sh           # lock-guarded ingest->cluster->score, for cron
  data/                    # gitignored: corroborate.duckdb, model.pkl
  tests/
    test_dedup.py
    test_cluster.py
```

---

## 6. Milestones

- **M0** ✅ Scaffold: repo, `pyproject.toml`, data model, DuckDB schema.
- **M1** ✅ USGS + EMSC ingest → `claims` / `ground_truth` populated.
- **M2** ✅ Dedup + ST-DBSCAN clustering → `events`.
- **M3** ✅ Feature extraction + calibrated scorer + reliability diagram.
- **M4** ✅ FastAPI GeoJSON endpoint.
- **M5** ✅ MapLibre map with score-colored markers + time slider.
- **M6** ✅ Social sources (Mastodon / Bluesky / X) + geoparse.
- **M7** ✅ Refutation flag end-to-end.

**Status:** M0–M7 complete — the full pipeline runs on live data.

**Live operation:** `run_cluster` is windowed + self-pruning and `score_events`
re-scores from the saved model, so `ingest → cluster → score_events` can run on a
loop with `train.py` recalibrating occasionally. `scripts/run_cycle.sh` sequences a
cycle under a lock (DuckDB is single-writer) for scheduling via cron — see README.

**Weekend cut:** M0–M5 on USGS + EMSC proves the core idea — an automated,
calibrated, independence-aware corroboration score validated against truth.

---

## 7. Dependencies

Managed with `uv` (per project preference — no pip).

Core: `duckdb`, `httpx`, `pydantic`, `numpy`, `scikit-learn`, `datasketch`,
`fastapi`, `uvicorn`.
Geoparse (M6): `geonamescache` (offline gazetteer).
Social (M6): `atproto` (Bluesky); X.com via plain `httpx` against API v2 + a
Bearer token in env (`X_BEARER_TOKEN`) — paid tier required.
Dev: `pytest`, `ruff`.

---

## 8. Open questions / decisions deferred

- Social geoparse precision is the biggest risk to score quality — may need a
  confidence floor that drops low-certainty geoparses rather than guessing.
- Reliability priors per source: start hand-set, later learn from history.
- Ground-truth match window (`Δd`, `Δt`) trades off label noise vs. coverage;
  sweep it during calibration.
