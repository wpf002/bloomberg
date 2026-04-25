from fastapi import APIRouter

from .routes import (
    alerts,
    auth,
    calendar,
    compare,
    crypto,
    explain,
    factors,
    filings,
    fixed_income,
    fundamentals,
    futures,
    fx,
    macro,
    me,
    news,
    options,
    orders,
    overview,
    portfolio,
    quotes,
    shared,
    sizing,
    sql,
    streams,
    symbols,
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
api_router.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(sizing.router, prefix="/sizing", tags=["sizing"])
api_router.include_router(explain.router, prefix="/explain", tags=["explain"])
api_router.include_router(compare.router, prefix="/compare", tags=["compare"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(streams.router, prefix="/ws", tags=["streams"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(shared.router, prefix="/shared", tags=["shared"])
api_router.include_router(sql.router, prefix="/sql", tags=["sql"])
api_router.include_router(factors.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(fixed_income.router, prefix="/fixed_income", tags=["fixed_income"])
api_router.include_router(futures.router, prefix="/futures", tags=["futures"])
api_router.include_router(symbols.router, prefix="/symbols", tags=["symbols"])

__all__ = ["api_router"]
