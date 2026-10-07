from fastapi import FastAPI

app = FastAPI(title="NBA Time Machine API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict[str, str]:
    return {
        "product": "NBA Time Machine",
        "spoiler_policy": "deterministic-firewall",
        "database": "neon-postgres-not-configured",
    }
