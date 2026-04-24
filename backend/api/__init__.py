from fastapi import APIRouter

from .routes import crypto, filings, macro, news, quotes

api_router = APIRouter()
api_router.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
api_router.include_router(macro.router, prefix="/macro", tags=["macro"])
api_router.include_router(crypto.router, prefix="/crypto", tags=["crypto"])
api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(filings.router, prefix="/filings", tags=["filings"])

__all__ = ["api_router"]
