"""Entry point of Core API: creates the FastAPI application and connects the modules.

Request path: uvicorn -> middleware (language) -> router of a module -> service -> database.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.auth.router import router as auth_router
from app.catalog.router import router as catalog_router
from app.common.config import get_settings
from app.common.db import get_engine
from app.common.errors import install_error_handlers
from app.common.i18n import locale_from_header, set_locale
from app.dictionaries.router import router as dictionaries_router
from app.orders.router import router as orders_router
from app.payments.router import router as payments_router
from app.users.router import router as users_router

app = FastAPI(
    title="OhBeat Core API",
    version="0.1.0",
    description="Marketplace of beats. Contracts: OhBeat-System-Analysis/03_API_and_Integrations/REST_API_Contracts.md",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def detect_language(request: Request, call_next):
    """NFR-26: error messages in the language of the Accept-Language header."""
    set_locale(locale_from_header(request.headers.get("accept-language")))
    return await call_next(request)


install_error_handlers(app)

API_PREFIX = "/v1"
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(dictionaries_router, prefix=API_PREFIX)
app.include_router(catalog_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(payments_router, prefix=API_PREFIX)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
