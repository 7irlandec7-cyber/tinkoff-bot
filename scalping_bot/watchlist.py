"""
Enhanced Watchlist with Volatile Stocks, Pairs and Futures
"""
from typing import Optional

# Основные акции MOEX (TQBR)
TQBR_STOCKS = [
    # Нефть и газ
    {"ticker": "GAZP", "figi": "BBG004730RP0", "name": "Газпром", "sector": "oil_gas", "volatility": "high"},
    {"ticker": "ROSN", "figi": "BBG004S681W1", "name": "Роснефть", "sector": "oil_gas", "volatility": "high"},
    {"ticker": "LKOH", "figi": "BBG004S68BJ8", "name": "Лукойл", "sector": "oil_gas", "volatility": "medium"},
    {"ticker": "NVTK", "figi": "BBG004S68B32", "name": "Новатэк", "sector": "oil_gas", "volatility": "high"},
    {"ticker": "TATN", "figi": "BBG004731096", "name": "Татнефть", "sector": "oil_gas", "volatility": "medium"},
    {"ticker": "SIBN", "figi": "BBG004731032", "name": "Газпромнефть", "sector": "oil_gas", "volatility": "medium"},
    
    # Металлы и добыча
    {"ticker": "GMKN", "figi": "BBG004S68BD5", "name": "Норникель", "sector": "metals", "volatility": "high"},
    {"ticker": "NLMK", "figi": "BBG004S681Z8", "name": "НЛМК", "sector": "metals", "volatility": "medium"},
    {"ticker": "CHMF", "figi": "BBG004S681L4", "name": "Северсталь", "sector": "metals", "volatility": "medium"},
    {"ticker": "ALRS", "figi": "BBG004S681J7", "name": "АЛРОСА", "sector": "metals", "volatility": "high"},
    {"ticker": "POLY", "figi": "BBG004S681H0", "name": "Полюс", "sector": "metals", "volatility": "high"},
    
    # Финансы
    {"ticker": "SBER", "figi": "BBG004S681F4", "name": "Сбербанк", "sector": "finance", "volatility": "medium"},
    {"ticker": "VTBR", "figi": "BBG004731148", "name": "ВТБ", "sector": "finance", "volatility": "high"},
    {"ticker": "TCSG", "figi": "BBG004S681B9", "name": "ТКС", "sector": "finance", "volatility": "medium"},
    {"ticker": "MOEX", "figi": "BBG004S681P8", "name": "МосБиржа", "sector": "finance", "volatility": "medium"},
    
    # Энергетика
    {"ticker": "IRKM", "figi": "BBG0047310L1", "name": "Иркут", "sector": "energy", "volatility": "high"},
    {"ticker": "UPRO", "figi": "BBG004731Y68", "name": "Юнипро", "sector": "energy", "volatility": "medium"},
    {"ticker": "FEES", "figi": "BBG004731L57", "name": "ФСК", "sector": "energy", "volatility": "medium"},
    {"ticker": "MSNG", "figi": "BBG0047310K3", "name": "Мосэнерго", "sector": "energy", "volatility": "medium"},
    {"ticker": "OGKB", "figi": "BBG004731Y50", "name": "ОГК-2", "sector": "energy", "volatility": "high"},
    {"ticker": "HYDR", "figi": "BBG004731L65", "name": "РусГидро", "sector": "energy", "volatility": "medium"},
    
    # Телекомы
    {"ticker": "MTSS", "figi": "BBG004S681D6", "name": "МТС", "sector": "telecom", "volatility": "low"},
    {"ticker": "VTKT", "figi": "BBG004731L73", "name": "ВТК", "sector": "telecom", "volatility": "high"},
    {"ticker": "MGTSP", "figi": "BBG004731R98", "name": "Мегафон", "sector": "telecom", "volatility": "medium"},
    
    # Потребительский сектор
    {"ticker": "X5RET", "figi": "BBG004S681N9", "name": "X5 Retail", "sector": "retail", "volatility": "medium"},
    {"ticker": "MAGN", "figi": "BBG004S681K8", "name": "ММК", "sector": "metals", "volatility": "medium"},
    {"ticker": "PIKK", "figi": "BBG004S68BH6", "name": "ПИК", "sector": "construction", "volatility": "high"},
    {"ticker": "LENT", "figi": "BBG004731ZT4", "name": "Лента", "sector": "retail", "volatility": "high"},
    {"ticker": "CBOM", "figi": "BBG009GSYN76", "name": "МКБ", "sector": "finance", "volatility": "high"},
    
    # IT
    {"ticker": "YDEX", "figi": "BBG00Q2K4L36", "name": "Яндекс", "sector": "it", "volatility": "high"},
    {"ticker": "VKCO", "figi": "TCS00A106YF0", "name": "VK", "sector": "it", "volatility": "high"},
    
    # Транспорт
    {"ticker": "AFLT", "figi": "BBG004S681Y3", "name": "Аэрофлот", "sector": "transport", "volatility": "high"},
    {"ticker": "FLOT", "figi": "BBG0047310V8", "name": "Совфрахт", "sector": "transport", "volatility": "high"},
    
    # Другое
    {"ticker": "AGRO", "figi": "BBG004731Z97", "name": "Аgroわ", "sector": "agriculture", "volatility": "medium"},
    {"ticker": "SELG", "figi": "BBG004S681M1", "name": "Селигдар", "sector": "mining", "volatility": "high"},
    {"ticker": "RASP", "figi": "BBG0047310F1", "name": "Распадская", "sector": "mining", "volatility": "high"},
    {"ticker": "SGZH", "figi": "BBG0047310C4", "name": "СГ-Транс", "sector": "transport", "volatility": "medium"},
    {"ticker": "TRNFP", "figi": "BBG0047310J5", "name": "Транснефть", "sector": "pipeline", "volatility": "low"},
]

# Фьючерсы MOEX
FUTURES = [
    {"ticker": "Si", "figi": "FUT-SI-12.24", "name": "USD/RUB", "type": "currency"},
    {"ticker": "BR", "figi": "FUT-BR-12.24", "name": "Brent", "type": "commodity"},
    {"ticker": "GOLD", "figi": "FUT-GOLD-12.24", "name": "Золото", "type": "commodity"},
]

# Коррелированные пары для парного трейдинга
TRADING_PAIRS = [
    # Пары нефтегаза
    {"long": "GAZP", "short": "NVTK", "name": "Газпром vs Новатэк", "sector": "oil_gas"},
    {"long": "ROSN", "short": "LKOH", "name": "Роснефть vs Лукойл", "sector": "oil_gas"},
    {"long": "TATN", "short": "SIBN", "name": "Татнефть vs Газпромнефть", "sector": "oil_gas"},
    
    # Пары металлов
    {"long": "GMKN", "short": "NLMK", "name": "Норникель vs НЛМК", "sector": "metals"},
    {"long": "GMKN", "short": "CHMF", "name": "Норникель vs Северсталь", "sector": "metals"},
    {"long": "NLMK", "short": "CHMF", "name": "НЛМК vs Северсталь", "sector": "metals"},
    
    # Пары энергетики
    {"long": "IRKM", "short": "MSNG", "name": "Иркут vs Мосэнерго", "sector": "energy"},
    {"long": "FEES", "short": "UPRO", "name": "ФСК vs Юнипро", "sector": "energy"},
    
    # Пары финансов
    {"long": "SBER", "short": "VTBR", "name": "Сбер vs ВТБ", "sector": "finance"},
    {"long": "CBOM", "short": "SBER", "name": "МКБ vs Сбер", "sector": "finance"},
    
    # IT пары
    {"long": "YDEX", "short": "VKCO", "name": "Яндекс vs VK", "sector": "it"},
]


def get_volatile_stocks_only():
    """Получить только высоковолатильные акции."""
    return [s for s in TQBR_STOCKS if s.get("volatility") == "high"]


def get_pairs_for_sector(sector: Optional[str] = None):
    """Получить пары для сектора."""
    if sector:
        return [p for p in TRADING_PAIRS if p.get("sector") == sector]
    return TRADING_PAIRS


def build_figi_map(stocks: Optional[list] = None, include_futures: bool = False) -> dict:
    """Построить mapping ticker -> figi."""
    result = {}
    items = stocks if stocks else TQBR_STOCKS
    
    for item in items:
        result[item["ticker"]] = item["figi"]
    
    if include_futures:
        for item in FUTURES:
            result[item["ticker"]] = item["figi"]
    
    return result


def get_all_figis(include_futures: bool = False, volatile_only: bool = False) -> list:
    """Получить все FIGI для мониторинга."""
    stocks = get_volatile_stocks_only() if volatile_only else TQBR_STOCKS
    figis = [s["figi"] for s in stocks]
    
    if include_futures:
        figis.extend([f["figi"] for f in FUTURES])
    
    return figis
