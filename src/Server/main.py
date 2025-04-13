from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from api.auth import router as auth_router
from api.websockets import ws_router
from analytics.routes import analysis_router

app = FastAPI()

app.allow_origins = ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],  # Allows POST, GET, OPTIONS, etc.
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")
app.include_router(ws_router, prefix="")
app.include_router(analysis_router, prefix="/analytics")
