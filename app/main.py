from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.incidents import router as incidents_router
from app.routers.chat import router as chat_router

app = FastAPI(title="Curiora-DevOps")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173",
    ],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)
app.include_router(incidents_router)
app.include_router(chat_router)
