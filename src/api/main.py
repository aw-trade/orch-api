from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import asyncio
from typing import Dict

from src.api.endpoints import simulation, results, analytics, resources
from src.database.postgres_client import postgres_client
from src.database.mongodb_client import mongodb_client
from src.services.simulator_service import SimulatorService
from src.services.redis_consumer import RedisStreamConsumer
from src.services.database_service import DatabaseService
from src.core.config import get_config

background_task_running = False
redis_consumer_running = False
app_config = get_config()
redis_consumer = None

async def redis_stream_consumption():
    """Background task to consume data from Redis streams"""
    global redis_consumer_running, redis_consumer
    redis_consumer_running = True
    
    logger = logging.getLogger(__name__)
    
    # Initialize Redis consumer with database service
    database_service = DatabaseService()
    redis_consumer = RedisStreamConsumer(database_service)
    
    try:
        # Connect to Redis and databases
        await database_service.connect()
        if not await redis_consumer.connect():
            logger.error("Failed to connect to Redis stream")
            return
        
        logger.info("🚀 Starting Redis stream consumption")
        
        # Start consuming messages
        await redis_consumer.start_consuming()
        
    except Exception as e:
        logger.error(f"Error in Redis stream consumption: {e}")
    finally:
        if redis_consumer:
            await redis_consumer.disconnect()
        await database_service.disconnect()
    
    logger.info("Redis stream consumption background task stopped")

async def periodic_stats_collection():
    """Legacy background task - kept for fallback if Redis is unavailable"""
    global background_task_running
    background_task_running = True
    
    logger = logging.getLogger(__name__)
    
    if not app_config.stats_collection.collection_enabled:
        logger.info("Periodic stats collection is disabled")
        return
    
    logger.info(f"Starting periodic stats collection (interval: {app_config.stats_collection.collection_interval_seconds}s)")
    
    failure_count = 0
    simulator = SimulatorService()
    
    while background_task_running:
        try:
            running_sims = simulator.get_running_simulations()
            
            if running_sims:
                logger.debug(f"Collecting stats for {len(running_sims)} running simulations")
            
            for run_id in running_sims:
                try:
                    live_stats = simulator.collect_live_stats(run_id)
                    if live_stats:
                        await store_periodic_stats(run_id, live_stats)
                        logger.debug(f"Stored periodic stats for {run_id}")
                    
                except Exception as e:
                    logger.warning(f"Failed to collect/store stats for {run_id}: {e}")
                    failure_count += 1
                    
                    if failure_count >= app_config.stats_collection.max_collection_failures:
                        backoff_time = app_config.stats_collection.collection_interval_seconds * app_config.stats_collection.failure_backoff_multiplier
                        logger.warning(f"Too many failures, backing off for {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        failure_count = 0
            
            if running_sims and failure_count == 0:
                failure_count = 0
            
            await asyncio.sleep(app_config.stats_collection.collection_interval_seconds)
            
        except Exception as e:
            logger.error(f"Error in periodic stats collection: {e}")
            failure_count += 1
            await asyncio.sleep(10)
    
    logger.info("Periodic stats collection background task stopped")

async def store_periodic_stats(run_id: str, stats: Dict):
    """Store periodic stats snapshot to database"""
    try:
        updates = {
            "total_pnl": stats.get("financials", {}).get("total_pnl", 0.0),
            "total_fees": stats.get("financials", {}).get("total_fees", 0.0),
            "net_pnl": stats.get("financials", {}).get("net_pnl", 0.0),
            "return_pct": stats.get("financials", {}).get("return_pct", 0.0),
            "max_drawdown": stats.get("financials", {}).get("max_drawdown", 0.0) / 100.0,
            "total_trades": stats.get("trades", {}).get("total", 0),
            "winning_trades": stats.get("trades", {}).get("winning", 0),
            "losing_trades": stats.get("trades", {}).get("losing", 0),
            "win_rate": stats.get("trades", {}).get("win_rate", 0.0) / 100.0,
            "signals_received": stats.get("signals", {}).get("received", 0),
            "signals_executed": stats.get("signals", {}).get("executed", 0),
            "execution_rate": stats.get("signals", {}).get("execution_rate", 0.0),
            "final_capital": stats.get("financials", {}).get("current_capital", 0.0)
        }
        
        await postgres_client.update_simulation_run(run_id, updates)
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to store periodic stats for {run_id}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task_running, redis_consumer_running, redis_consumer
    
    # Startup
    logging.basicConfig(level=logging.INFO)
    await postgres_client.connect()
    await mongodb_client.connect()
    
    # Start Redis stream consumer (primary method)
    redis_task = asyncio.create_task(redis_stream_consumption())
    
    # Start legacy HTTP polling as fallback (optional)
    background_task = None
    if app_config.stats_collection.collection_enabled:
        background_task = asyncio.create_task(periodic_stats_collection())
    
    yield
    
    # Shutdown
    redis_consumer_running = False
    if redis_consumer:
        await redis_consumer.stop_consuming()
    
    background_task_running = False
    
    # Cancel tasks
    redis_task.cancel()
    if background_task:
        background_task.cancel()
    
    try:
        await redis_task
    except asyncio.CancelledError:
        pass
    
    if background_task:
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    
    await postgres_client.disconnect()
    await mongodb_client.disconnect()

app = FastAPI(
    title="Trading Simulator Orchestration API",
    description="API for managing trading algorithm simulations with persistent storage",
    version="2.0.0",
    lifespan=lifespan
)

# Include routers
app.include_router(simulation.router)
app.include_router(results.router)
app.include_router(analytics.router)
app.include_router(resources.router)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        postgres_healthy = postgres_client.connection_pool is not None
        mongo_healthy = mongodb_client.client is not None
        
        from src.services.resource_manager import ResourceManager
        from src.services.simulator_service import SimulatorService
        
        resource_manager = ResourceManager(SimulatorService())
        resource_status = resource_manager.check_resource_limits()
        
        redis_healthy = redis_consumer is not None and redis_consumer_running
        
        return {
            "status": "healthy" if postgres_healthy and mongo_healthy else "degraded",
            "databases": {
                "postgresql": "connected" if postgres_healthy else "disconnected",
                "mongodb": "connected" if mongo_healthy else "disconnected",
                "redis": "connected" if redis_healthy else "disconnected"
            },
            "resources": {
                "active_simulations": resource_status["active_runs"],
                "at_limit": resource_status["at_limit"],
                "warnings": resource_status["warnings"]
            },
            "data_collection": {
                "redis_streams": {
                    "enabled": True,
                    "running": redis_consumer_running
                },
                "legacy_http_polling": {
                    "enabled": app_config.stats_collection.collection_enabled,
                    "interval_seconds": app_config.stats_collection.collection_interval_seconds,
                    "running": background_task_running
                }
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@app.get("/health/redis-consumer")
async def redis_consumer_health():
    """Redis consumer health and statistics endpoint"""
    try:
        if not redis_consumer:
            return {
                "status": "not_initialized",
                "message": "Redis consumer not initialized"
            }
        
        # Get consumer statistics
        stats = redis_consumer.get_consumer_stats()
        
        # Get Redis stream info
        stream_info = await redis_consumer.get_stream_info()
        
        # Determine health status
        status = "healthy"
        if not stats["is_running"]:
            status = "stopped"
        elif not stats["connected"]:
            status = "disconnected"
        elif stats["database_write_failures"] > 0:
            failure_rate = stats["database_write_failures"] / (stats["database_write_success"] + stats["database_write_failures"])
            if failure_rate > 0.1:  # More than 10% failures
                status = "degraded"
        
        return {
            "status": status,
            "consumer_stats": stats,
            "stream_info": stream_info,
            "health_indicators": {
                "is_running": stats["is_running"],
                "connected": stats["connected"],
                "messages_processed": stats["messages_processed"],
                "database_write_success": stats["database_write_success"],
                "database_write_failures": stats["database_write_failures"],
                "success_rate": stats.get("success_rate", 0),
                "messages_per_second": stats.get("messages_per_second", 0),
                "last_message_time": stats["last_message_time"],
                "last_error": stats["last_error"]
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/debug/redis-messages")
async def debug_redis_messages():
    """Debug endpoint to check recent Redis messages"""
    try:
        if not redis_consumer or not redis_consumer.redis_client:
            return {
                "error": "Redis consumer not available"
            }
        
        # Get recent messages from the stream
        messages = await redis_consumer.redis_client.xrevrange(
            app_config.database.redis_stream_name,
            count=10
        )
        
        formatted_messages = []
        for msg_id, fields in messages:
            formatted_messages.append({
                "id": msg_id,
                "timestamp": msg_id.split('-')[0],
                "fields": fields
            })
        
        return {
            "stream_name": app_config.database.redis_stream_name,
            "recent_messages": formatted_messages,
            "message_count": len(formatted_messages)
        }
    except Exception as e:
        return {
            "error": str(e)
        }

@app.get("/config")
async def get_configuration():
    """Get current application configuration"""
    return {
        "stats_collection": {
            "enabled": app_config.stats_collection.collection_enabled,
            "interval_seconds": app_config.stats_collection.collection_interval_seconds,
            "timeout_seconds": app_config.stats_collection.collection_timeout_seconds,
            "max_failures": app_config.stats_collection.max_collection_failures,
            "failure_backoff_multiplier": app_config.stats_collection.failure_backoff_multiplier
        },
        "database": {
            "max_retries": app_config.database.max_retries,
            "retry_delay": app_config.database.retry_delay,
            "circuit_breaker_threshold": app_config.database.circuit_breaker_threshold,
            "circuit_breaker_reset_timeout": app_config.database.circuit_breaker_reset_timeout,
            "backup_dir": app_config.database.backup_dir
        },
        "simulator": {
            "default_results_timeout": app_config.simulator.default_results_timeout,
            "max_result_retries": app_config.simulator.max_result_retries,
            "max_concurrent_simulations": app_config.simulator.max_concurrent_simulations
        },
        "environment": app_config.environment,
        "debug": app_config.debug
    }

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)