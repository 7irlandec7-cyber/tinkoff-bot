"""
Хранение позиций и цен входа.
"""
import json
import os
from datetime import datetime
from typing import Dict, Optional

POSITIONS_FILE = "/tmp/scalping_positions.json"


def save_positions(positions: list) -> None:
    """Сохранить текущие позиции в файл."""
    data = {
        "saved_at": datetime.now().isoformat(),
        "positions": [
            {
                "figi": p.figi,
                "ticker": p.ticker,
                "direction": p.direction,
                "entry_price": p.entry_price,
                "quantity": p.quantity,
                "entry_time": p.entry_time.isoformat() if hasattr(p, 'entry_time') else datetime.now().isoformat(),
                # Биржевой SL должен переживать рестарт бота: иначе бот теряет учёт
                # своих стопов и либо дублирует их, либо оставляет «сиротскими».
                "exchange_sl_order_id": getattr(p, "exchange_sl_order_id", None),
                "exchange_sl_price": getattr(p, "exchange_sl_price", None),
                # Биржевой TP — для отображения в терминале Т-Инвестиций
                "exchange_tp_order_id": getattr(p, "exchange_tp_order_id", None),
                "exchange_tp_price": getattr(p, "exchange_tp_price", None)
            }
            for p in positions
        ]
    }
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_positions() -> Dict[str, Dict]:
    """Загрузить сохранённые позиции."""
    if not os.path.exists(POSITIONS_FILE):
        return {}
    
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        
        result = {}
        for p in data.get("positions", []):
            result[p["figi"]] = p
        
        return result
    except Exception as e:
        print(f"Ошибка загрузки позиций: {e}")
        return {}


def clear_positions() -> None:
    """Очистить сохранённые позиции."""
    if os.path.exists(POSITIONS_FILE):
        os.remove(POSITIONS_FILE)
