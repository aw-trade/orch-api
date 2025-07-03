from fastapi import APIRouter

from src.database.models import SimulationStatus
from src.database.postgres_client import postgres_client
from src.database.mongodb_client import mongodb_client

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/summary")
async def get_analytics_summary():
    """Get summary analytics across all simulations"""
    recent_runs = await postgres_client.list_simulation_runs(limit=10)
    
    config_stats = await mongodb_client.get_config_stats()
    
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