"""Configuration settings for the trading simulator orchestration API"""

import os
from typing import Optional
from pydantic import BaseModel


class DatabaseConfig(BaseModel):
    """Database connection and retry configuration"""
    max_retries: int = int(os.getenv("DB_MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("DB_RETRY_DELAY", "1.0"))
    circuit_breaker_threshold: int = int(os.getenv("DB_CIRCUIT_BREAKER_THRESHOLD", "5"))
    circuit_breaker_reset_timeout: int = int(os.getenv("DB_CIRCUIT_BREAKER_RESET", "60"))
    backup_dir: str = os.getenv("BACKUP_DIR", "./data/backup")
    
    # PostgreSQL specific
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "trading_results")
    postgres_user: str = os.getenv("POSTGRES_USER", "trading_user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "trading_pass")
    
    # MongoDB specific
    mongodb_url: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "trading_configs")
    
    # Redis specific
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_stream_name: str = os.getenv("REDIS_STREAM_NAME", "trading-stats")


class StatsCollectionConfig(BaseModel):
    """Configuration for periodic stats collection"""
    collection_interval_seconds: int = int(os.getenv("STATS_COLLECTION_INTERVAL", "30"))
    collection_enabled: bool = os.getenv("STATS_COLLECTION_ENABLED", "true").lower() == "true"
    collection_timeout_seconds: int = int(os.getenv("STATS_COLLECTION_TIMEOUT", "5"))
    max_collection_failures: int = int(os.getenv("STATS_MAX_FAILURES", "3"))
    failure_backoff_multiplier: float = float(os.getenv("STATS_FAILURE_BACKOFF", "2.0"))


class SimulatorConfig(BaseModel):
    """Configuration for simulator service"""
    default_results_timeout: int = int(os.getenv("SIMULATOR_RESULTS_TIMEOUT", "10"))
    max_result_retries: int = int(os.getenv("SIMULATOR_MAX_RETRIES", "5"))
    docker_cleanup_interval: int = int(os.getenv("DOCKER_CLEANUP_INTERVAL", "300"))  # 5 minutes
    max_concurrent_simulations: int = int(os.getenv("MAX_CONCURRENT_SIMULATIONS", "10"))


class ApiConfig(BaseModel):
    """API server configuration"""
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = int(os.getenv("API_PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_origins: list = os.getenv("CORS_ORIGINS", "*").split(",")
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))


class AppConfig(BaseModel):
    """Main application configuration"""
    database: DatabaseConfig = DatabaseConfig()
    stats_collection: StatsCollectionConfig = StatsCollectionConfig()
    simulator: SimulatorConfig = SimulatorConfig()
    api: ApiConfig = ApiConfig()
    
    # Environment
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


# Global configuration instance
config = AppConfig()


def get_config() -> AppConfig:
    """Get the global configuration instance"""
    return config


def reload_config() -> AppConfig:
    """Reload configuration from environment variables"""
    global config
    config = AppConfig()
    return config