from fastapi import FastAPI
from .demo_app import router

app = FastAPI(title="GuardBench controlled HTTP fixtures")
app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True, "fixture": True}
