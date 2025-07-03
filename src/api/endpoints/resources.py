from fastapi import APIRouter, Depends

from src.services.resource_manager import ResourceManager
from src.services.simulator_service import SimulatorService

router = APIRouter(prefix="/resources", tags=["resources"])

async def get_resource_manager():
    simulator = SimulatorService()
    return ResourceManager(simulator)

@router.get("/usage")
async def get_resource_usage(resource_manager: ResourceManager = Depends(get_resource_manager)):
    """Get current Docker resource usage"""
    return resource_manager.get_docker_resource_usage()

@router.get("/limits")
async def check_resource_limits(resource_manager: ResourceManager = Depends(get_resource_manager)):
    """Check if approaching resource limits"""
    return resource_manager.check_resource_limits()

@router.post("/cleanup")
async def cleanup_resources(resource_manager: ResourceManager = Depends(get_resource_manager)):
    """Clean up orphaned Docker resources"""
    return resource_manager.full_cleanup()