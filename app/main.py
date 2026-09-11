from fastapi import FastAPI

from app.routers.incidents import router as incidents_router


app = FastAPI(title="Curiora-DevOps")
app.include_router(incidents_router)
