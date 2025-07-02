from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import logging
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

# Database lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.basicConfig(level=logging.INFO)
    await postgres_client.connect()
    await mongodb_client.connect()
    yield
    # Shutdown
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
    
    #run_saved = await postgres_client.create_simulation_run(simulation_run)
    #if not run_saved:
    #    raise HTTPException(status_code=500, detail="Failed to create simulation run record")
    
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
            # Update status in both databases
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
        # Update status in both databases
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
        # Update database status
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
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)