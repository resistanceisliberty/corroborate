"""FastAPI: serve scored events as GeoJSON + the static MapLibre frontend.

Run: uv run uvicorn corroborate.api:app --reload
Then open http://127.0.0.1:8000/

Endpoints:
  GET /events.geojson?since=<iso8601>&min_score=<float>  -> FeatureCollection
  GET /health
The frontend in web/ is mounted at / (so the map and API share an origin).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db

app = FastAPI(title="Corroborate")


def build_feature_collection(con, since: str | None = None, min_score: float = 0.0) -> dict:
    """Assemble scored events (with their corroborating sources) as GeoJSON."""
    rows = con.execute(
        """
        SELECT e.event_id, e.centroid_lat, e.centroid_lon, e.est_time,
               e.score, e.n_claims, e.n_independent, e.n_source_types,
               e.refutation_flag,
               array_agg(DISTINCT c.source_id) FILTER (WHERE c.source_id IS NOT NULL) AS sources,
               max(c.magnitude) AS max_mag
        FROM events e
        LEFT JOIN event_claims j ON e.event_id = j.event_id
        LEFT JOIN claims c ON j.claim_id = c.claim_id
        WHERE (?::TIMESTAMP IS NULL OR e.est_time >= ?::TIMESTAMP)
          AND coalesce(e.score, 0) >= ?
        GROUP BY e.event_id, e.centroid_lat, e.centroid_lon, e.est_time,
                 e.score, e.n_claims, e.n_independent, e.n_source_types,
                 e.refutation_flag
        ORDER BY coalesce(e.score, 0) DESC
        """,
        [since, since, min_score],
    ).fetchall()

    features = []
    for (eid, lat, lon, est, score, n_claims, n_ind, n_types, refute, sources, max_mag) in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "event_id": str(eid),
                    "score": score,
                    "n_claims": n_claims,
                    "n_independent": n_ind,
                    "n_source_types": n_types,
                    "refutation_flag": bool(refute) if refute is not None else False,
                    "est_time": est.isoformat() if est else None,
                    "sources": list(sources) if sources else [],
                    "max_magnitude": max_mag,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/events.geojson")
def events_geojson(since: str | None = None, min_score: float = 0.0):
    if since is not None:
        try:
            datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="`since` must be an ISO-8601 timestamp"
            ) from exc
    con = db.connect(read_only=True)
    try:
        return JSONResponse(build_feature_collection(con, since, min_score))
    finally:
        con.close()


# Static frontend mounted last so the API routes above take precedence.
app.mount("/", StaticFiles(directory=str(config.ROOT / "web"), html=True), name="web")
