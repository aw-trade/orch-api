from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager

from simulator_service import SimulatorService
from resource_manager import ResourceManager
from database.models import (
    StartSimulationRequest, StartSimulationResponse, SimulationStatusResponse,
    SimulationResultsResponse, SimulationSummary, AlgoConfig, SimulatorConfig,
    SimulationConfigDocument, SimulationRun, SimulationStatus
)
from database.postgres_client import postgres_client
from database.mongodb_client import mongodb_client
from config import get_config

# Global background task control
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
    
    while background_task_running:
        try:
            # Get all running simulations
            running_sims = simulator.get_running_simulations()
            
            if running_sims:
                logger.debug(f"Collecting stats for {len(running_sims)} running simulations")
            
            for run_id in running_sims:
                try:
                    # Collect live stats with configured timeout
                    live_stats = simulator.collect_live_stats(run_id)
                    if live_stats:
                        # Store periodic snapshot to database
                        await store_periodic_stats(run_id, live_stats)
                        logger.debug(f"Stored periodic stats for {run_id}")
                    
                except Exception as e:
                    logger.warning(f"Failed to collect/store stats for {run_id}: {e}")
                    failure_count += 1
                    
                    # Implement backoff if too many failures
                    if failure_count >= app_config.stats_collection.max_collection_failures:
                        backoff_time = app_config.stats_collection.collection_interval_seconds * app_config.stats_collection.failure_backoff_multiplier
                        logger.warning(f"Too many failures, backing off for {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        failure_count = 0
            
            # Reset failure count on successful round
            if running_sims and failure_count == 0:
                failure_count = 0
            
            # Wait configured interval before next collection
            await asyncio.sleep(app_config.stats_collection.collection_interval_seconds)
            
        except Exception as e:
            logger.error(f"Error in periodic stats collection: {e}")
            failure_count += 1
            await asyncio.sleep(10)  # Wait a bit before retrying
    
    logger.info("Periodic stats collection background task stopped")

async def store_periodic_stats(run_id: str, stats: Dict):
    """Store periodic stats snapshot to database"""
    try:
        # Map live stats to database update format
        updates = {
            "total_pnl": stats.get("financials", {}).get("total_pnl", 0.0),
            "total_fees": stats.get("financials", {}).get("total_fees", 0.0),
            "net_pnl": stats.get("financials", {}).get("net_pnl", 0.0),
            "return_pct": stats.get("financials", {}).get("return_pct", 0.0),
            "max_drawdown": stats.get("financials", {}).get("max_drawdown", 0.0) / 100.0,  # Convert from percentage
            "total_trades": stats.get("trades", {}).get("total", 0),
            "winning_trades": stats.get("trades", {}).get("winning", 0),
            "losing_trades": stats.get("trades", {}).get("losing", 0),
            "win_rate": stats.get("trades", {}).get("win_rate", 0.0) / 100.0,  # Convert from percentage
            "signals_received": stats.get("signals", {}).get("received", 0),
            "signals_executed": stats.get("signals", {}).get("executed", 0),
            "execution_rate": stats.get("signals", {}).get("execution_rate", 0.0),
            "final_capital": stats.get("financials", {}).get("current_capital", 0.0)
        }
        
        # Update simulation run with current stats
        await postgres_client.update_simulation_run(run_id, updates)
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to store periodic stats for {run_id}: {e}")

# Database lifecycle management
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
simulator = SimulatorService()
resource_manager = ResourceManager(simulator)

async def persist_simulation_results(run_id: str, results: Dict):
    """Persist collected simulation results to PostgreSQL"""
    try:
        # Extract relevant data from results
        end_time = datetime.now()
        
        # Map Rust SimulationStats to our database fields
        updates = {
            "status": SimulationStatus.COMPLETED.value,
            "end_time": end_time,
            "final_capital": results.get("final_capital", 0.0),
            "total_pnl": results.get("total_pnl", 0.0),
            "total_fees": results.get("total_fees", 0.0),
            "net_pnl": results.get("net_pnl", 0.0),
            "return_pct": results.get("return_pct", 0.0),
            "max_drawdown": results.get("max_drawdown", 0.0),
            "total_trades": results.get("total_trades", 0),
            "winning_trades": results.get("winning_trades", 0),
            "losing_trades": results.get("losing_trades", 0),
            "win_rate": results.get("win_rate", 0.0),
            "signals_received": results.get("signals_received", 0),
            "signals_executed": results.get("signals_executed", 0),
            "execution_rate": results.get("signals_executed", 0) / max(results.get("signals_received", 1), 1) * 100.0,
            "total_volume": results.get("total_volume", 0.0),
            "sharpe_ratio": results.get("sharpe_ratio", 0.0),
            "avg_win": results.get("avg_win", 0.0),
            "avg_loss": results.get("avg_loss", 0.0)
        }
        
        # Update simulation run in PostgreSQL
    
        await postgres_client.update_simulation_run(run_id, updates)
        
        # Update status in MongoDB
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.COMPLETED.value})
        
        logging.info(f"Successfully persisted results for simulation {run_id}")
        
    except Exception as e:
        logging.error(f"Failed to persist results for {run_id}: {e}")

# Models are now imported from database.models

class StopSimulationResponse(BaseModel):
    success: bool
    message: str
    run_id: Optional[str] = None

@app.post("/simulate/start", response_model=StartSimulationResponse)
async def start_simulation(request: StartSimulationRequest):
    if request.duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Duration must be positive")
    
    # Generate unique run ID
    run_id = f"run_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    
    # Use defaults if configs not provided
    algo_config = request.algo_consts or AlgoConfig()
    simulator_config = request.simulator_consts or SimulatorConfig()
    
    # Save configuration to MongoDB
    config_doc = SimulationConfigDocument(
        run_id=run_id,
        created_at=datetime.now(),
        status=SimulationStatus.PENDING,
        duration_seconds=request.duration_seconds,
        algorithm_version=request.algorithm_version,
        algo_config=algo_config,
        simulator_config=simulator_config,
        metadata=request.metadata
    )
    
    config_saved = await mongodb_client.save_simulation_config(config_doc)
    if not config_saved:
        raise HTTPException(status_code=500, detail="Failed to save simulation configuration")
    
    # Create simulation run record in PostgreSQL
    simulation_run = SimulationRun(
        run_id=run_id,
        start_time=datetime.now(),
        duration_seconds=request.duration_seconds,
        algorithm_version=request.algorithm_version,
        status=SimulationStatus.PENDING,
        initial_capital=simulator_config.INITIAL_CAPITAL
    )
    run_saved = await postgres_client.create_simulation_run(simulation_run)
    if not run_saved:
        raise HTTPException(status_code=500, detail="Failed to create simulation run record")
    
    # Start the simulation
    success = simulator.start_simulation(
        run_id,
        request.duration_seconds,
        algo_config,
        simulator_config
    )
    
    if success:
        # Update status to running in both databases
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.RUNNING.value})
        await postgres_client.update_simulation_run(run_id, {"status": SimulationStatus.RUNNING.value})
        
        return StartSimulationResponse(
            success=True,
            message=f"Simulation started for {request.duration_seconds} seconds",
            run_id=run_id
        )
    else:
        # Update status to failed
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.FAILED.value})
        await postgres_client.update_simulation_run(run_id, {"status": SimulationStatus.FAILED.value})
        
        current_status = simulator.get_status()
        if current_status["status"] == "error":
            raise HTTPException(status_code=500, detail="Failed to start simulation")
        else:
            raise HTTPException(status_code=500, detail="Failed to start simulation")

@app.get("/simulate/status")
async def get_simulation_status():
    """Get status of all running simulations"""
    status = simulator.get_status()
    return status

@app.get("/simulate/status/{run_id}")
async def get_specific_simulation_status(run_id: str):
    """Get status of a specific simulation"""
    status = simulator.get_status(run_id)
    return status

@app.get("/simulate/runs", response_model=List[SimulationSummary])
async def list_simulation_runs(
    limit: int = 100,
    offset: int = 0,
    status: Optional[SimulationStatus] = None,
    algorithm_version: Optional[str] = None
):
    """List all simulation runs with filtering"""
    runs = await postgres_client.list_simulation_runs(limit, offset, status, algorithm_version)
    return [
        SimulationSummary(
            run_id=run.run_id,
            start_time=run.start_time,
            end_time=run.end_time,
            duration_seconds=run.duration_seconds,
            status=run.status,
            algorithm_version=run.algorithm_version or "unknown",
            net_pnl=run.net_pnl,
            return_pct=run.return_pct,
            total_trades=run.total_trades,
            win_rate=run.win_rate
        )
        for run in runs
    ]

@app.get("/simulate/runs/{run_id}", response_model=SimulationStatusResponse)
async def get_simulation_run_status(run_id: str):
    """Get status of a specific simulation run"""
    # Get from PostgreSQL
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    # Calculate elapsed and remaining time
    elapsed_seconds = None
    remaining_seconds = None
    
    if simulation.start_time:
        elapsed = datetime.now() - simulation.start_time
        elapsed_seconds = int(elapsed.total_seconds())
        
        if simulation.status == SimulationStatus.RUNNING:
            remaining_seconds = max(0, simulation.duration_seconds - elapsed_seconds)
    
    return SimulationStatusResponse(
        run_id=simulation.run_id,
        status=simulation.status,
        start_time=simulation.start_time.isoformat() if simulation.start_time else None,
        end_time=simulation.end_time.isoformat() if simulation.end_time else None,
        duration_seconds=simulation.duration_seconds,
        elapsed_seconds=elapsed_seconds,
        remaining_seconds=remaining_seconds
    )

@app.post("/simulate/stop", response_model=StopSimulationResponse)
async def stop_all_simulations():
    """Stop all currently running simulations"""
    results = simulator.stop_all_simulations()
    
    if not results:
        raise HTTPException(status_code=409, detail="No simulations running")
    
    stopped_runs = []
    failed_runs = []
    
    for run_id, success in results.items():
        if success:
            # Check if we have collected results to persist
            collected_results = simulator.get_simulation_results(run_id)
            if collected_results:
                await persist_simulation_results(run_id, collected_results)
            else:
                # Update status in both databases without results
                await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
                await postgres_client.update_simulation_run(run_id, {
                    "status": SimulationStatus.STOPPED.value,
                    "end_time": datetime.now()
                })
            stopped_runs.append(run_id)
        else:
            failed_runs.append(run_id)
    
    if failed_runs:
        return StopSimulationResponse(
            success=False,
            message=f"Stopped {len(stopped_runs)} simulations, failed to stop {len(failed_runs)}: {', '.join(failed_runs)}"
        )
    else:
        return StopSimulationResponse(
            success=True,
            message=f"Successfully stopped {len(stopped_runs)} simulations: {', '.join(stopped_runs)}"
        )

@app.post("/simulate/stop/{run_id}", response_model=StopSimulationResponse)
async def stop_specific_simulation(run_id: str):
    """Stop a specific simulation run"""
    # Check if the run exists in the database
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    # Attempt to stop the simulation
    success = simulator.stop_simulation(run_id)
    
    if success:
        # Check if we have collected results to persist
        collected_results = simulator.get_simulation_results(run_id)
        if collected_results:
            await persist_simulation_results(run_id, collected_results)
        else:
            # Update status in both databases without results
            await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
            await postgres_client.update_simulation_run(run_id, {
                "status": SimulationStatus.STOPPED.value,
                "end_time": datetime.now()
            })
        
        return StopSimulationResponse(
            success=True,
            message=f"Simulation {run_id} stopped successfully",
            run_id=run_id
        )
    else:
        # Check if it's already stopped or if it's an error
        sim_status = simulator.get_status(run_id)
        if sim_status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Simulation not currently active")
        else:
            raise HTTPException(status_code=500, detail="Failed to stop simulation")

@app.get("/results/{run_id}", response_model=SimulationResultsResponse)
async def get_simulation_results(run_id: str):
    """Get complete results for a simulation run"""
    # Get simulation run
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    # Get configuration
    config = await mongodb_client.get_simulation_config(run_id)
    if not config:
        raise HTTPException(status_code=404, detail="Simulation configuration not found")
    
    # Get trades and positions
    trades = await postgres_client.get_trades(run_id)
    positions = await postgres_client.get_positions(run_id)
    
    return SimulationResultsResponse(
        run_id=run_id,
        simulation=simulation,
        trades=trades,
        positions=positions,
        config=config
    )

@app.get("/results/{run_id}/trades")
async def get_simulation_trades(run_id: str):
    """Get trade history for a simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    trades = await postgres_client.get_trades(run_id)
    return {"run_id": run_id, "trades": trades}

@app.get("/results/{run_id}/positions")
async def get_simulation_positions(run_id: str):
    """Get final positions for a simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    positions = await postgres_client.get_positions(run_id)
    return {"run_id": run_id, "positions": positions}

@app.get("/analytics/summary")
async def get_analytics_summary():
    """Get summary analytics across all simulations"""
    # Get recent runs
    recent_runs = await postgres_client.list_simulation_runs(limit=10)
    
    # Get config statistics
    config_stats = await mongodb_client.get_config_stats()
    
    # Calculate basic metrics
    completed_runs = [r for r in recent_runs if r.status == SimulationStatus.COMPLETED]
    
    avg_return = 0.0
    if completed_runs:
        returns = [r.return_pct for r in completed_runs if r.return_pct is not None]
        avg_return = sum(returns) / len(returns) if returns else 0.0
    
    return {
        "recent_runs": len(recent_runs),
        "completed_runs": len(completed_runs),
        "average_return_pct": avg_return,
        "configuration_stats": config_stats
    }

@app.get("/resources/usage")
async def get_resource_usage():
    """Get current Docker resource usage"""
    return resource_manager.get_docker_resource_usage()

@app.get("/resources/limits")
async def check_resource_limits():
    """Check if approaching resource limits"""
    return resource_manager.check_resource_limits()

@app.post("/resources/cleanup")
async def cleanup_resources():
    """Clean up orphaned Docker resources"""
    return resource_manager.full_cleanup()

@app.post("/simulate/force-stop/{run_id}")
async def force_stop_simulation(run_id: str):
    """Force stop a simulation (emergency stop)"""
    success = resource_manager.force_stop_simulation(run_id)
    
    if success:
        # Try to collect results even for force stop
        collected_results = simulator.get_simulation_results(run_id)
        if collected_results:
            await persist_simulation_results(run_id, collected_results)
        else:
            # Update database status without results
            await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
            await postgres_client.update_simulation_run(run_id, {
                "status": SimulationStatus.STOPPED.value,
                "end_time": datetime.now()
            })
        
        return {"success": True, "message": f"Simulation {run_id} force stopped"}
    else:
        raise HTTPException(status_code=500, detail="Failed to force stop simulation")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connections
        postgres_healthy = postgres_client.connection_pool is not None
        mongo_healthy = mongodb_client.client is not None
        
        # Check resource status
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