"""Public entry point for the synthetic allocation review."""
from fastapi import Request
from fastapi.responses import JSONResponse
from app import app as original

from fastapi import FastAPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
paths = {
    "/", "/api/health", "/api/state", "/api/market-watch",
    "/api/external/status", "/api/allocation/evidence",
    "/api/allocation/policy-example", "/api/allocation/compare",
    "/api/scenario", "/api/report", "/api/references",
}

@app.middleware("http")
async def demo_scope(request: Request, call_next):
    path = request.url.path
    if path not in paths and not path.startswith("/static/"):
        return JSONResponse({"detail": "공개 데모에서는 가상 데이터 배분 기능을 사용할 수 있습니다."}, status_code=403)
    if request.method == "POST" and request.headers.get("origin") not in (None, str(request.base_url).rstrip("/")):
        return JSONResponse({"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403)
    return await call_next(request)

app.mount("/", original)
