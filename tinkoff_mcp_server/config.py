"""
Tinkoff MCP Server - Configuration Module
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Tinkoff API
    tinkoff_token: str = ""
    tinkoff_account_id: Optional[str] = None
    tinkoff_api_url: str = "https://invest-public-api.tinkoff.ru/rest"
    
    # MCP Server
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8000
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "tinkoff_mcp.log"
    
    # Trading
    dry_run: bool = True
    max_position_size: float = 10000.0
    max_daily_loss: float = 500.0
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore unknown fields like TELEGRAM_BOT_TOKEN


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings


def validate_config() -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []
    
    if not settings.tinkoff_token:
        errors.append("TINKOFF_TOKEN is required")
    
    if settings.max_position_size <= 0:
        errors.append("MAX_POSITION_SIZE must be positive")
    
    if settings.max_daily_loss <= 0:
        errors.append("MAX_DAILY_LOSS must be positive")
    
    return errors
