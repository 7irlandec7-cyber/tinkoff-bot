"""
Tinkoff MCP Client - Mean Reversion Strategy
"""
from typing import Dict, Any, List, Optional
from .base import BaseStrategy, Signal, Candle, Position


class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy.
    
    Buys when price is significantly below the moving average,
    sells when price is significantly above.
    
    Key assumptions:
    - Prices tend to revert to their mean over time
    - Extreme deviations create high-probability reversal opportunities
    """
    
    name = "mean_reversion"
    description = "Mean Reversion - buys at lows, sells at highs"
    
    def _parse_params(self) -> Dict[str, Any]:
        """Parse mean reversion specific parameters."""
        params = super()._parse_params()
        params.update({
            "ma_period": self.config.get("ma_period", 20),
            "std_period": self.config.get("std_period", 20),
            "buy_threshold": self.config.get("buy_threshold", -2.0),  # 2 std deviations below MA
            "sell_threshold": self.config.get("sell_threshold", 2.0),  # 2 std above MA
            "zscore_buy": self.config.get("zscore_buy", -1.5),
            "zscore_sell": self.config.get("zscore_sell", 1.5),
            "holding_period": self.config.get("holding_period", 5),  # Max bars to hold
        })
        return params
    
    def analyze(self, candles: List[Candle]) -> Dict[str, Any]:
        """
        Analyze candles for mean reversion signals.
        
        Args:
            candles: List of historical candles
            
        Returns:
            Dictionary with MA, std deviation, and z-score
        """
        min_required = max(self.params["ma_period"], self.params["std_period"])
        if len(candles) < min_required + 1:
            return {"valid": False, "error": "Insufficient data"}
        
        closes = [c.close for c in candles]
        
        # Calculate moving average
        ma = self._calculate_sma(closes, self.params["ma_period"])
        
        # Calculate rolling standard deviation
        std = self._calculate_rolling_std(closes, self.params["std_period"])
        
        # Calculate z-score
        current_price = closes[-1]
        zscore = (current_price - ma) / std if std > 0 else 0
        
        # Calculate deviation from MA (percentage)
        deviation_percent = (current_price - ma) / ma * 100 if ma > 0 else 0
        
        # Calculate RSI for confirmation
        rsi = self._calculate_rsi(closes)
        
        # Bollinger Bands
        upper_band = ma + (std * 2)
        lower_band = ma - (std * 2)
        bandwidth = (upper_band - lower_band) / ma * 100 if ma > 0 else 0
        
        # Price position within bands (0 = lower, 100 = upper)
        band_position = 50  # default middle
        if upper_band != lower_band:
            band_position = (current_price - lower_band) / (upper_band - lower_band) * 100
        
        return {
            "valid": True,
            "current_price": current_price,
            "ma": ma,
            "std": std,
            "zscore": zscore,
            "deviation_percent": deviation_percent,
            "rsi": rsi,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "bandwidth": bandwidth,
            "band_position": band_position,
            "prices": closes
        }
    
    def _calculate_sma(self, data: List[float], period: int) -> float:
        """Calculate Simple Moving Average."""
        if len(data) < period:
            return data[-1] if data else 0
        return sum(data[-period:]) / period
    
    def _calculate_rolling_std(self, data: List[float], period: int) -> float:
        """Calculate rolling standard deviation."""
        if len(data) < period:
            return 0
        
        subset = data[-period:]
        mean = sum(subset) / period
        variance = sum((x - mean) ** 2 for x in subset) / period
        return variance ** 0.5
    
    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index."""
        if len(closes) < period + 1:
            return 50.0
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def should_buy(
        self,
        analysis: Dict[str, Any],
        current_price: float,
        portfolio: List[Position]
    ) -> Optional[Signal]:
        """
        Determine if should buy based on mean reversion signals.
        
        BUY signals:
        - Price significantly below MA (large negative deviation)
        - Z-score below threshold
        - RSI confirming oversold
        """
        if not analysis.get("valid"):
            return None
        
        zscore = analysis["zscore"]
        rsi = analysis["rsi"]
        deviation = analysis["deviation_percent"]
        band_position = analysis["band_position"]
        
        # Count signals
        signals = []
        confidence = 0.0
        
        # Extreme z-score (price far below mean)
        if zscore <= self.params["zscore_buy"]:
            signals.append(f"Z-score: {zscore:.2f}")
            confidence += 0.35
        
        # Large deviation from MA
        if deviation <= self.params["buy_threshold"]:
            signals.append(f"Deviation: {deviation:.1f}%")
            confidence += 0.25
        
        # RSI confirming oversold
        if rsi < 35:
            signals.append(f"RSI: {rsi:.1f} (oversold)")
            confidence += 0.25
        
        # Near lower Bollinger Band
        if band_position < 20:
            signals.append(f"Price at {band_position:.0f}% of band range")
            confidence += 0.15
        
        if confidence >= self.params["min_confidence"]:
            return Signal(
                action="BUY",
                confidence=confidence,
                reason=f"Mean reversion BUY: {', '.join(signals)}",
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
        Determine if should sell based on mean reversion signals.
        
        SELL signals:
        - Price significantly above MA
        - Z-score above threshold
        - Stop loss or take profit hit
        """
        if not analysis.get("valid"):
            return None
        
        # Check stop loss
        if self.check_stop_loss(position, current_price):
            return Signal(
                action="SELL",
                confidence=1.0,
                reason=f"Stop loss ({self.params['stop_loss_percent']}%)",
                price=current_price
            )
        
        # Check take profit
        if self.check_take_profit(position, current_price):
            return Signal(
                action="SELL",
                confidence=0.95,
                reason=f"Take profit ({self.params['take_profit_percent']}%)",
                price=current_price
            )
        
        zscore = analysis["zscore"]
        rsi = analysis["rsi"]
        deviation = analysis["deviation_percent"]
        band_position = analysis["band_position"]
        
        signals = []
        confidence = 0.0
        
        # Extreme z-score (price far above mean)
        if zscore >= self.params["zscore_sell"]:
            signals.append(f"Z-score: {zscore:.2f}")
            confidence += 0.35
        
        # Large positive deviation from MA
        if deviation >= self.params["sell_threshold"]:
            signals.append(f"Deviation: {deviation:.1f}%")
            confidence += 0.25
        
        # RSI confirming overbought
        if rsi > 65:
            signals.append(f"RSI: {rsi:.1f} (overbought)")
            confidence += 0.25
        
        # Near upper Bollinger Band
        if band_position > 80:
            signals.append(f"Price at {band_position:.0f}% of band range")
            confidence += 0.15
        
        if confidence >= self.params["min_confidence"]:
            return Signal(
                action="SELL",
                confidence=confidence,
                reason=f"Mean reversion SELL: {', '.join(signals)}",
                price=current_price
            )
        
        return None
