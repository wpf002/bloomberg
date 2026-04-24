from fastapi import APIRouter

from .routes import (
    calendar,
    crypto,
    filings,
    fundamentals,
    fx,
    macro,
    news,
    options,
    overview,
    quotes,
)

api_router = APIRouter()
api_router.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
api_router.include_router(macro.router, prefix="/macro", tags=["macro"])
api_router.include_router(crypto.router, prefix="/crypto", tags=["crypto"])
api_router.include_router(fx.router, prefix="/fx", tags=["fx"])
api_router.include_router(options.router, prefix="/options", tags=["options"])
api_router.include_router(overview.router, prefix="/overview", tags=["overview"])
api_router.include_router(fundamentals.router, prefix="/fundamentals", tags=["fundamentals"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(filings.router, prefix="/filings", tags=["filings"])

__all__ = ["api_router"]
