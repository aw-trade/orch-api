from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import asyncio
from typing import Dict

from src.api.endpoints import simulation, results, analytics, resources
from src.database.postgres_client import postgres_client
from src.database.mongodb_client import mongodb_client
from src.services.simulator_service import SimulatorService
from src.core.config import get_config

background_task_running = False
app_config = get_config()

async def periodic_stats_collection():
    """Background task to collect live stats periodically from running simulations"""
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
    global background_task_running
    
    # Startup
    logging.basicConfig(level=logging.INFO)
    await postgres_client.connect()
    await mongodb_client.connect()
    
    # Start background task
    background_task = asyncio.create_task(periodic_stats_collection())
    
    yield
    
    # Shutdown
    background_task_running = False
    background_task.cancel()
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
        
        return {
            "status": "healthy" if postgres_healthy and mongo_healthy else "degraded",
            "databases": {
                "postgresql": "connected" if postgres_healthy else "disconnected",
                "mongodb": "connected" if mongo_healthy else "disconnected"
            },
            "resources": {
                "active_simulations": resource_status["active_runs"],
                "at_limit": resource_status["at_limit"],
                "warnings": resource_status["warnings"]
            },
            "stats_collection": {
                "enabled": app_config.stats_collection.collection_enabled,
                "interval_seconds": app_config.stats_collection.collection_interval_seconds,
                "running": background_task_running
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
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