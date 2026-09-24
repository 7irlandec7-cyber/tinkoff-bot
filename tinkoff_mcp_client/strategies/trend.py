"""
Tinkoff MCP Client - Trend Following Strategy
"""
from typing import Dict, Any, List, Optional
from .base import BaseStrategy, Signal, Candle, Position


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend Following Strategy.
    
    Uses moving averages to identify and follow trends.
    - BUY when short MA crosses above long MA (golden cross)
    - SELL when short MA crosses below long MA (death cross)
    """
    
    name = "trend_following"
    description = "Trend Following - follows trends using moving averages"
    
    def _parse_params(self) -> Dict[str, Any]:
        """Parse trend-following specific parameters."""
        params = super()._parse_params()
        params.update({
            "fast_ma": self.config.get("fast_ma", 20),
            "slow_ma": self.config.get("slow_ma", 50),
            "signal_ma": self.config.get("signal_ma", 9),  # MACD signal line
            "atr_period": self.config.get("atr_period", 14),
            "atr_multiplier": self.config.get("atr_multiplier", 2.0)
        })
        return params
    
    def analyze(self, candles: List[Candle]) -> Dict[str, Any]:
        """
        Analyze candles for trend indicators.
        
        Args:
            candles: List of historical candles
            
        Returns:
            Dictionary with MA crossover and trend indicators
        """
        min_required = max(self.params["slow_ma"], self.params["signal_ma"])
        if len(candles) < min_required + 5:
            return {"valid": False, "error": "Insufficient data"}
        
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        
        # Calculate Moving Averages
        fast_ma = self._calculate_sma(closes, self.params["fast_ma"])
        slow_ma = self._calculate_sma(closes, self.params["slow_ma"])
        
        # Calculate EMA for signal line
        ema = self._calculate_ema(closes, self.params["signal_ma"])
        
        # Calculate MACD
        macd_line = fast_ma - slow_ma
        macd_signal = ema
        
        # Previous values for crossover detection
        prev_fast_ma = self._calculate_sma(closes[:-1], self.params["fast_ma"])
        prev_slow_ma = self._calculate_sma(closes[:-1], self.params["slow_ma"])
        
        # Calculate ATR for stop loss
        atr = self._calculate_atr(candles, self.params["atr_period"])
        
        # Determine trend
        trend = "neutral"
        if fast_ma > slow_ma and fast_ma > slow_ma * 1.01:
            trend = "uptrend"
        elif fast_ma < slow_ma and fast_ma < slow_ma * 0.99:
            trend = "downtrend"
        
        # Detect crossover
        golden_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
        death_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma
        
        return {
            "valid": True,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_line - macd_signal,
            "atr": atr,
            "trend": trend,
            "golden_cross": golden_cross,
            "death_cross": death_cross,
            "current_price": closes[-1],
            "prices": closes
        }
    
    def _calculate_sma(self, data: List[float], period: int) -> float:
        """Calculate Simple Moving Average."""
        if len(data) < period:
            return data[-1] if data else 0
        return sum(data[-period:]) / period
    
    def _calculate_ema(self, data: List[float], period: int) -> float:
        """Calculate Exponential Moving Average."""
        if len(data) < period:
            return data[-1] if data else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_atr(self, candles: List[Candle], period: int) -> float:
        """Calculate Average True Range."""
        if len(candles) < period + 1:
            return 0
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        return sum(true_ranges[-period:]) / period if true_ranges else 0
    
    def should_buy(
        self,
        analysis: Dict[str, Any],
        current_price: float,
        portfolio: List[Position]
    ) -> Optional[Signal]:
        """
        Determine if should buy based on trend following signals.
        
        BUY signals:
        - Golden cross (fast MA crosses above slow MA)
        - Strong uptrend with MACD histogram positive
        """
        if not analysis.get("valid"):
            return None
        
        golden_cross = analysis["golden_cross"]
        trend = analysis["trend"]
        macd_histogram = analysis["macd_histogram"]
        atr = analysis["atr"]
        
        # Strong buy signal on golden cross
        if golden_cross and trend == "uptrend":
            confidence = 0.85
            if macd_histogram > 0:
                confidence = 0.95
            
            return Signal(
                action="BUY",
                confidence=confidence,
                reason=f"Golden cross detected. Fast MA > Slow MA. Trend: {trend}",
                price=current_price
            )
        
        # Trend following buy
        if trend == "uptrend" and macd_histogram > 0:
            confidence = self.params["min_confidence"]
            if macd_histogram > atr * 0.5:
                confidence = 0.8
            
            return Signal(
                action="BUY",
                confidence=confidence,
                reason=f"Uptrend continuation. MACD histogram positive. ATR: {atr:.2f}",
                price=current_price
            )
        
        return None
    
    def should_sell(
        self,
        analysis: Dict[str, Any],
        position: Position,
        current_price: float
    ) -> Optional[Signal]:
        """
        Determine if should sell based on trend reversal.
        
        SELL signals:
        - Death cross (fast MA crosses below slow MA)
        - Stop loss based on ATR
        - Trend changes to downtrend
        """
        if not analysis.get("valid"):
            return None
        
        # Check stop loss (ATR-based trailing stop)
        atr = analysis["atr"]
        stop_loss_price = position.average_price - atr * self.params["atr_multiplier"]
        if current_price <= stop_loss_price:
            return Signal(
                action="SELL",
                confidence=1.0,
                reason=f"ATR stop loss triggered (price {current_price:.2f} <= {stop_loss_price:.2f})",
                price=current_price
            )
        
        # Check standard stop loss
        if self.check_stop_loss(position, current_price):
            return Signal(
                action="SELL",
                confidence=1.0,
                reason=f"Stop loss triggered ({self.params['stop_loss_percent']}%)",
                price=current_price
            )
        
        # Check take profit
        if self.check_take_profit(position, current_price):
            return Signal(
                action="SELL",
                confidence=0.9,
                reason=f"Take profit triggered ({self.params['take_profit_percent']}%)",
                price=current_price
            )
        
        death_cross = analysis["death_cross"]
        trend = analysis["trend"]
        
        # Death cross is strong sell signal
        if death_cross:
            return Signal(
                action="SELL",
                confidence=0.9,
                reason="Death cross detected. Fast MA crossed below Slow MA.",
                price=current_price
            )
        
        # Trend reversal
        if trend == "downtrend":
            return Signal(
                action="SELL",
                confidence=0.75,
                reason=f"Trend changed to downtrend",
                price=current_price
            )
        
        return None
