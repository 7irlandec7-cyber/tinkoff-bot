"""
Tinkoff MCP Client - Base Strategy Class
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class Signal:
    """Trading signal."""
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0 to 1.0
    reason: str
    price: Optional[float] = None
    quantity: Optional[int] = None


@dataclass
class Candle:
    """Price candle data."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Position:
    """Portfolio position."""
    figi: str
    ticker: str
    name: str
    quantity: int
    average_price: float
    current_value: float
    profit: float
    profit_percent: float


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""
    
    name: str = "base"
    description: str = "Base trading strategy"
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize strategy.
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.params = self._parse_params()
    
    def _parse_params(self) -> Dict[str, Any]:
        """Parse strategy-specific parameters."""
        return {
            "min_confidence": self.config.get("min_confidence", 0.6),
            "max_position_size": self.config.get("max_position_size", 10000),
            "stop_loss_percent": self.config.get("stop_loss_percent", 5.0),
            "take_profit_percent": self.config.get("take_profit_percent", 10.0)
        }
    
    @abstractmethod
    def analyze(self, candles: List[Candle]) -> Dict[str, Any]:
        """
        Analyze candles and return analysis data.
        
        Args:
            candles: List of historical candles
            
        Returns:
            Dictionary with analysis results
        """
        pass
    
    def should_buy(
        self,
        analysis: Dict[str, Any],
        current_price: float,
        portfolio: List[Position]
    ) -> Optional[Signal]:
        """
        Determine if should buy.
        
        Args:
            analysis: Analysis results from analyze()
            current_price: Current instrument price
            portfolio: Current portfolio positions
            
        Returns:
            Signal if should buy, None otherwise
        """
        return None
    
    def should_sell(
        self,
        analysis: Dict[str, Any],
        position: Position,
        current_price: float
    ) -> Optional[Signal]:
        """
        Determine if should sell position.
        
        Args:
            analysis: Analysis results from analyze()
            position: Position to potentially sell
            current_price: Current instrument price
            
        Returns:
            Signal if should sell, None otherwise
        """
        return None
    
    def calculate_quantity(
        self,
        price: float,
        available_cash: float
    ) -> int:
        """
        Calculate position size.
        
        Args:
            price: Current price
            available_cash: Available cash for buying
            
        Returns:
            Number of lots to buy
        """
        max_amount = min(
            self.params["max_position_size"],
            available_cash * 0.1  # Use max 10% of portfolio
        )
        return int(max_amount / price)
    
    def check_stop_loss(
        self,
        position: Position,
        current_price: float
    ) -> bool:
        """
        Check if position hit stop loss.
        
        Args:
            position: Current position
            current_price: Current price
            
        Returns:
            True if stop loss triggered
        """
        loss_percent = (position.average_price - current_price) / position.average_price * 100
        return loss_percent >= self.params["stop_loss_percent"]
    
    def check_take_profit(
        self,
        position: Position,
        current_price: float
    ) -> bool:
        """
        Check if position hit take profit.
        
        Args:
            position: Current position
            current_price: Current price
            
        Returns:
            True if take profit triggered
        """
        profit_percent = (current_price - position.average_price) / position.average_price * 100
        return profit_percent >= self.params["take_profit_percent"]
