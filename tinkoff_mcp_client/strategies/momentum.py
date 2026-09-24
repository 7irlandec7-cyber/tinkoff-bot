"""
Tinkoff MCP Client - Momentum Trading Strategy
"""
from typing import Dict, Any, List, Optional
from .base import BaseStrategy, Signal, Candle, Position


class MomentumStrategy(BaseStrategy):
    """
    Momentum Trading Strategy.
    
    Buys when price shows strong upward momentum and sells when momentum weakens.
    Uses RSI and price rate of change for signal generation.
    """
    
    name = "momentum"
    description = "Momentum Trading - buys on strong uptrend, sells on reversal"
    
    def _parse_params(self) -> Dict[str, Any]:
        """Parse momentum-specific parameters."""
        params = super()._parse_params()
        params.update({
            "rsi_period": self.config.get("rsi_period", 14),
            "rsi_oversold": self.config.get("rsi_oversold", 30),
            "rsi_overbought": self.config.get("rsi_overbought", 70),
            "roc_period": self.config.get("roc_period", 10),
            "roc_threshold": self.config.get("roc_threshold", 3.0),  # 3% ROC
            "volume_confirmation": self.config.get("volume_confirmation", True),
            "volume_threshold": self.config.get("volume_threshold", 1.5)  # 1.5x average
        })
        return params
    
    def analyze(self, candles: List[Candle]) -> Dict[str, Any]:
        """
        Analyze candles for momentum indicators.
        
        Args:
            candles: List of historical candles
            
        Returns:
            Dictionary with RSI, ROC, and momentum indicators
        """
        if len(candles) < max(self.params["rsi_period"], self.params["roc_period"]):
            return {"valid": False, "error": "Insufficient data"}
        
        closes = [c.close for c in candles]
        
        # Calculate RSI
        rsi = self._calculate_rsi(closes)
        
        # Calculate Rate of Change
        roc = self._calculate_roc(closes)
        
        # Calculate volume average
        volumes = [c.volume for c in candles]
        avg_volume = sum(volumes[-self.params["rsi_period"]:]) / self.params["rsi_period"]
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Trend strength
        prices_20 = closes[-20:] if len(closes) >= 20 else closes
        trend_strength = (closes[-1] - prices_20[0]) / prices_20[0] * 100 if prices_20 else 0
        
        return {
            "valid": True,
            "rsi": rsi,
            "roc": roc,
            "trend_strength": trend_strength,
            "volume_ratio": volume_ratio,
            "current_price": closes[-1],
            "prices": closes
        }
    
    def _calculate_rsi(self, closes: List[float]) -> float:
        """Calculate Relative Strength Index."""
        period = self.params["rsi_period"]
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
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_roc(self, closes: List[float]) -> float:
        """Calculate Rate of Change percentage."""
        period = self.params["roc_period"]
        if len(closes) < period + 1:
            return 0.0
        
        current = closes[-1]
        past = closes[-period - 1]
        roc = (current - past) / past * 100
        return roc
    
    def should_buy(
        self,
        analysis: Dict[str, Any],
        current_price: float,
        portfolio: List[Position]
    ) -> Optional[Signal]:
        """
        Determine if should buy based on momentum signals.
        
        BUY signals:
        - RSI exits oversold territory (crossed above 30)
        - ROC > threshold (strong momentum)
        - Volume confirmation enabled and volume > threshold
        """
        if not analysis.get("valid"):
            return None
        
        rsi = analysis["rsi"]
        roc = analysis["roc"]
        volume_ratio = analysis["volume_ratio"]
        
        # Check if already holding this instrument
        # (In real implementation, would check specific ticker)
        
        # Strong momentum buy signal
        momentum_score = 0
        reasons = []
        
        # RSI in oversold and turning up
        if rsi < self.params["rsi_oversold"]:
            momentum_score += 0.4
            reasons.append(f"RSI oversold ({rsi:.1f})")
        
        # Strong ROC
        if roc > self.params["roc_threshold"]:
            momentum_score += 0.3
            reasons.append(f"Strong ROC ({roc:.2f}%)")
        
        # Volume confirmation
        if self.params["volume_confirmation"] and volume_ratio > self.params["volume_threshold"]:
            momentum_score += 0.3
            reasons.append(f"High volume ({volume_ratio:.1f}x avg)")
        
        # Require minimum confidence
        confidence = momentum_score
        if confidence >= self.params["min_confidence"]:
            return Signal(
                action="BUY",
                confidence=confidence,
                reason="Momentum: " + ", ".join(reasons),
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
        Determine if should sell based on momentum reversal.
        
        SELL signals:
        - RSI in overbought territory
        - Negative ROC (momentum fading)
        - Stop loss or take profit hit
        """
        if not analysis.get("valid"):
            return None
        
        # Check stop loss
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
        
        rsi = analysis["rsi"]
        roc = analysis["roc"]
        
        sell_score = 0
        reasons = []
        
        # RSI overbought
        if rsi > self.params["rsi_overbought"]:
            sell_score += 0.4
            reasons.append(f"RSI overbought ({rsi:.1f})")
        
        # Negative or weak momentum
        if roc < 0:
            sell_score += 0.3
            reasons.append(f"Weak momentum (ROC: {roc:.2f}%)")
        elif roc < self.params["roc_threshold"] / 2:
            sell_score += 0.15
            reasons.append(f"Fading momentum (ROC: {roc:.2f}%)")
        
        confidence = sell_score
        if confidence >= self.params["min_confidence"]:
            return Signal(
                action="SELL",
                confidence=confidence,
                reason="Momentum reversal: " + ", ".join(reasons),
                price=current_price
            )
        
        return None
