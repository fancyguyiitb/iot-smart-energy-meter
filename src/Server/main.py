from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from analytics.routes import analysis_router
from api.auth import router as auth_router
from api.routes import router as api_router
from api.websockets import ws_router
from config import settings
from storage import close_store, get_store
from utils.database import get_metadata_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_metadata_db()  # create tables
    get_store()
    yield
    close_store()


app = FastAPI(title="Voltix server", lifespan=lifespan)

# Explicit origins: "*" together with credentials is rejected by browsers' CORS rules and,
# with Starlette's echo-the-origin behaviour, effectively allowed every site.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,  # the API uses bearer tokens, not cookies
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")
app.include_router(ws_router, prefix="")
app.include_router(analysis_router, prefix="/analytics")

# The web client (src/WebApp) is static and same-origin locally; in the cloud it can be
# served from a CDN instead and pointed at this API.
if settings.webapp_dir.is_dir():
    app.mount("/app", StaticFiles(directory=settings.webapp_dir, html=True), name="webapp")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/app/")
