import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.core.cache import query_cache
from backend.core.router import route_query
from backend.models.query import ExecuteRequest

router = APIRouter()


@router.post("/execute")
@router.post("/sql/execute")
async def execute(req: ExecuteRequest) -> dict[str, Any]:
    cache_key = hashlib.sha256(f"{req.source}|{req.mode}|{req.query}".encode("utf-8")).hexdigest()
    cached = query_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    try:
        payload = route_query(req.query, req.mode, req.source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = {
        "result": payload.get("result"),
        "rows": payload.get("rows", payload.get("result")),
        "columns": payload.get("columns", []),
        "time": payload.get("time", 0.0),
        "approx": payload.get("approx", False),
        "sample_rate": payload.get("sample_rate"),
        "source": payload.get("source", req.source),
        "rewritten_query": payload.get("rewritten_query"),
        "cached": False,
    }

    query_cache.set(cache_key, response)
    return response
