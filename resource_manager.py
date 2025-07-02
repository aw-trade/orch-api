import subprocess
import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from simulator_service import SimulatorService

logger = logging.getLogger(__name__)


class ResourceManager:
    """Manages Docker resources and provides cleanup utilities for simulations"""
    
    def __init__(self, simulator_service: SimulatorService):
        self.simulator_service = simulator_service
        self.max_concurrent_runs = 10  # Configurable limit
        self.resource_check_interval = 60  # seconds
        
    def get_docker_resource_usage(self) -> Dict[str, any]:
        """Get current Docker resource usage"""
        try:
            # Get container count
            result = subprocess.run(
                ['docker', 'ps', '-q'], 
                capture_output=True, text=True
            )
            container_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            
            # Get network count (trading networks only)
            result = subprocess.run(
                ['docker', 'network', 'ls', '--filter', 'name=trading-network', '-q'], 
                capture_output=True, text=True
            )
            network_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            
            # Get system info
            result = subprocess.run(
                ['docker', 'system', 'df', '--format', 'json'], 
                capture_output=True, text=True
            )
            
            return {
                "container_count": container_count,
                "network_count": network_count,
                "timestamp": datetime.now().isoformat(),
                "active_simulations": len(self.simulator_service.get_active_run_ids())
            }
            
        except Exception as e:
            logger.error(f"Failed to get Docker resource usage: {e}")
            return {"error": str(e)}
    
    def cleanup_orphaned_containers(self) -> Dict[str, List[str]]:
        """Clean up containers that belong to stopped simulations"""
        cleaned_containers = []
        failed_cleanups = []
        
        try:
            # Get all containers with simulation-related names
            result = subprocess.run([
                'docker', 'ps', '-a', '--filter', 'name=market-streamer-', 
                '--filter', 'name=order-book-algo-', '--filter', 'name=trade-simulator-',
                '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": "Failed to list containers"}
            
            container_names = result.stdout.strip().split('\n') if result.stdout.strip() else []
            active_run_ids = set(self.simulator_service.get_active_run_ids())
            
            for container_name in container_names:
                # Extract run_id from container name
                run_id = None
                for service_prefix in ['market-streamer-', 'order-book-algo-', 'trade-simulator-']:
                    if container_name.startswith(service_prefix):
                        run_id = container_name[len(service_prefix):]
                        break
                
                # If run_id is not in active runs, clean it up
                if run_id and run_id not in active_run_ids:
                    try:
                        # Stop and remove container
                        subprocess.run(['docker', 'stop', container_name], 
                                     capture_output=True, check=False)
                        result = subprocess.run(['docker', 'rm', container_name], 
                                              capture_output=True, text=True)
                        if result.returncode == 0:
                            cleaned_containers.append(container_name)
                        else:
                            failed_cleanups.append(container_name)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup container {container_name}: {e}")
                        failed_cleanups.append(container_name)
            
            return {
                "cleaned_containers": cleaned_containers,
                "failed_cleanups": failed_cleanups
            }
            
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned containers: {e}")
            return {"error": str(e)}
    
    def cleanup_orphaned_networks(self) -> Dict[str, List[str]]:
        """Clean up networks that belong to stopped simulations"""
        cleaned_networks = []
        failed_cleanups = []
        
        try:
            # Get all trading networks
            result = subprocess.run([
                'docker', 'network', 'ls', '--filter', 'name=trading-network-',
                '--format', '{{.Name}}'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": "Failed to list networks"}
            
            network_names = result.stdout.strip().split('\n') if result.stdout.strip() else []
            active_run_ids = set(self.simulator_service.get_active_run_ids())
            
            for network_name in network_names:
                if network_name.startswith('trading-network-'):
                    run_id = network_name[len('trading-network-'):]
                    
                    # If run_id is not in active runs, clean it up
                    if run_id not in active_run_ids:
                        try:
                            result = subprocess.run(['docker', 'network', 'rm', network_name], 
                                                  capture_output=True, text=True)
                            if result.returncode == 0:
                                cleaned_networks.append(network_name)
                            else:
                                failed_cleanups.append(network_name)
                        except Exception as e:
                            logger.warning(f"Failed to cleanup network {network_name}: {e}")
                            failed_cleanups.append(network_name)
            
            return {
                "cleaned_networks": cleaned_networks,
                "failed_cleanups": failed_cleanups
            }
            
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned networks: {e}")
            return {"error": str(e)}
    
    def full_cleanup(self) -> Dict[str, any]:
        """Perform a comprehensive cleanup of all orphaned resources"""
        logger.info("Starting full resource cleanup")
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "containers": self.cleanup_orphaned_containers(),
            "networks": self.cleanup_orphaned_networks()
        }
        
        # Also cleanup compose files
        try:
            compose_files = self.simulator_service.compose_generator.list_active_compose_files()
            active_run_ids = set(self.simulator_service.get_active_run_ids())
            
            cleaned_compose_files = []
            for run_id in compose_files:
                if run_id not in active_run_ids:
                    self.simulator_service.compose_generator.cleanup_compose_file(run_id)
                    cleaned_compose_files.append(run_id)
            
            results["compose_files"] = {"cleaned": cleaned_compose_files}
            
        except Exception as e:
            results["compose_files"] = {"error": str(e)}
        
        logger.info(f"Cleanup completed: {results}")
        return results
    
    def check_resource_limits(self) -> Dict[str, any]:
        """Check if we're approaching resource limits"""
        active_runs = len(self.simulator_service.get_active_run_ids())
        resource_usage = self.get_docker_resource_usage()
        
        warnings = []
        
        if active_runs >= self.max_concurrent_runs:
            warnings.append(f"Maximum concurrent runs reached: {active_runs}/{self.max_concurrent_runs}")
        
        if resource_usage.get("container_count", 0) > 50:
            warnings.append(f"High container count: {resource_usage['container_count']}")
        
        return {
            "active_runs": active_runs,
            "max_concurrent_runs": self.max_concurrent_runs,
            "resource_usage": resource_usage,
            "warnings": warnings,
            "at_limit": active_runs >= self.max_concurrent_runs
        }
    
    def force_stop_simulation(self, run_id: str) -> bool:
        """Force stop a simulation even if the normal stop process fails"""
        try:
            # Get compose file path
            compose_file_path = self.simulator_service.compose_generator.get_compose_file_path(run_id)
            
            # Force stop containers
            result = subprocess.run([
                'docker', 'compose', '-f', compose_file_path, 'kill'
            ], capture_output=True, text=True, cwd='.')
            
            if result.returncode != 0:
                logger.warning(f"docker compose kill failed for {run_id}: {result.stderr}")
            
            # Force remove containers and networks
            result = subprocess.run([
                'docker', 'compose', '-f', compose_file_path, 'down', '--volumes', '--remove-orphans'
            ], capture_output=True, text=True, cwd='.')
            
            if result.returncode != 0:
                logger.warning(f"docker compose down failed for {run_id}: {result.stderr}")
            
            # Clean up compose file
            self.simulator_service.compose_generator.cleanup_compose_file(run_id)
            
            # Remove from active runs if present
            if run_id in self.simulator_service.active_runs:
                del self.simulator_service.active_runs[run_id]
            
            logger.info(f"Force stopped simulation {run_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to force stop simulation {run_id}: {e}")
            return False