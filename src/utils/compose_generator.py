import yaml
import os
from typing import Dict, Any, Optional
from src.database.models import AlgoConfig, SimulatorConfig


class ComposeGenerator:
    """Generates dynamic docker-compose files for parallel simulation runs"""
    
    def __init__(self, template_path: str = "docker/docker-compose.yml"):
        self.template_path = template_path
        self.compose_dir = "docker/compose_files"
        os.makedirs(self.compose_dir, exist_ok=True)
    
    def generate_compose_file(self, 
                            run_id: str, 
                            algo_config: Optional[AlgoConfig] = None,
                            simulator_config: Optional[SimulatorConfig] = None,
                            duration_seconds: Optional[int] = None) -> str:
        """Generate a unique docker-compose file for a simulation run"""
        
        # Load template
        with open(self.template_path, 'r') as f:
            template = yaml.safe_load(f)
        
        # Generate unique identifiers
        network_name = f"trading-network-{run_id}"
        
        # Port assignments (base ports + hash of run_id for uniqueness)
        port_offset = abs(hash(run_id)) % 10000
        market_streamer_port = 8001 + port_offset
        order_book_port = 8002 + port_offset
        trade_sim_port = 8003 + port_offset
        results_api_port = 8080 + port_offset
        signal_port = 9999 + port_offset
        
        # Create new compose structure
        compose = {
            "services": {},
            "networks": {
                network_name: {
                    "driver": "bridge"
                },
                "external": {
                    "external": True,
                    "name": "trading-db-network"
                }
            }
        }
        
        # Market Streamer service
        compose["services"][f"market-streamer-{run_id}"] = {
            "image": "market-streamer:latest",
            "container_name": f"market-streamer-{run_id}",
            "pull_policy": "never",
            "networks": [network_name],
            "ports": [f"{market_streamer_port}:8001"],
            "environment": [
                "BIND_ADDR=0.0.0.0:8888",
                f"SIMULATION_RUN_ID={run_id}"
            ],
            "expose": ["8888"]
        }
        
        # Order Book Algorithm service
        order_book_env = [
            f"STREAMING_SOURCE_IP=market-streamer-{run_id}",
            "STREAMING_SOURCE_PORT=8888",
            "POSTGRES_HOST=postgres",
            "POSTGRES_PORT=5432",
            "POSTGRES_DB=trading_results",
            "POSTGRES_USER=trading_user",
            "POSTGRES_PASSWORD=trading_pass",
            "MONGODB_HOST=mongodb",
            "MONGODB_PORT=27017",
            "MONGODB_USERNAME=admin",
            "MONGODB_PASSWORD=admin_pass",
            "MONGODB_DATABASE=trading_configs",
            f"SIMULATION_RUN_ID={run_id}"
        ]
        
        # Add algorithm configuration
        if algo_config:
            for key, value in algo_config.dict().items():
                if value is not None:
                    order_book_env.append(f"{key}={value}")
        
        compose["services"][f"order-book-algo-{run_id}"] = {
            "image": "order-book-algo:latest",
            "container_name": f"order-book-algo-{run_id}",
            "pull_policy": "never",
            "depends_on": [f"market-streamer-{run_id}"],
            "networks": [network_name, "external"],
            "ports": [
                f"{order_book_port}:8002",
                f"{signal_port}:9999"
            ],
            "environment": order_book_env,
            "expose": ["9999"]
        }
        
        # Trade Simulator service
        simulator_env = [
            f"ALGORITHM_SOURCE_IP=order-book-algo-{run_id}",
            "ALGORITHM_SOURCE_PORT=9999",
            "LISTEN_PORT=9999",
            "POSTGRES_HOST=postgres",
            "POSTGRES_PORT=5432",
            "POSTGRES_DB=trading_results",
            "POSTGRES_USER=trading_user",
            "POSTGRES_PASSWORD=trading_pass",
            "MONGODB_HOST=mongodb",
            "MONGODB_PORT=27017",
            "MONGODB_USERNAME=admin",
            "MONGODB_PASSWORD=admin_pass",
            "MONGODB_DATABASE=trading_configs",
            f"SIMULATION_RUN_ID={run_id}",
            "REDIS_HOST=redis",
            "REDIS_PORT=6379"
        ]
        
        # Add simulator configuration
        if simulator_config:
            for key, value in simulator_config.dict().items():
                if value is not None:
                    simulator_env.append(f"{key}={value}")
        
        # Add MAX_RUNTIME_SECS from duration_seconds parameter
        if duration_seconds is not None:
            simulator_env.append(f"MAX_RUNTIME_SECS={duration_seconds}")
        
        compose["services"][f"trade-simulator-{run_id}"] = {
            "image": "trade-simulator:latest",
            "container_name": f"trade-simulator-{run_id}",
            "pull_policy": "never",
            "depends_on": [f"order-book-algo-{run_id}"],
            "networks": [network_name, "external"],
            "ports": [
                f"{trade_sim_port}:8003",
                f"{results_api_port}:8080"
            ],
            "environment": simulator_env
        }
        
        # Write compose file
        compose_file_path = os.path.join(self.compose_dir, f"docker-compose-{run_id}.yml")
        with open(compose_file_path, 'w') as f:
            yaml.dump(compose, f, default_flow_style=False)
        
        return compose_file_path
    
    def cleanup_compose_file(self, run_id: str):
        """Remove the compose file for a completed simulation"""
        compose_file_path = os.path.join(self.compose_dir, f"docker-compose-{run_id}.yml")
        try:
            if os.path.exists(compose_file_path):
                os.remove(compose_file_path)
        except Exception as e:
            print(f"Warning: Failed to cleanup compose file for {run_id}: {e}")
    
    def get_compose_file_path(self, run_id: str) -> str:
        """Get the path to the compose file for a run"""
        return os.path.join(self.compose_dir, f"docker-compose-{run_id}.yml")
    
    def get_results_api_port(self, run_id: str) -> int:
        """Get the results API port for a specific run_id"""
        port_offset = abs(hash(run_id)) % 10000
        return 8080 + port_offset
    
    def list_active_compose_files(self) -> list:
        """List all active compose files"""
        if not os.path.exists(self.compose_dir):
            return []
        
        files = []
        for filename in os.listdir(self.compose_dir):
            if filename.startswith("docker-compose-") and filename.endswith(".yml"):
                run_id = filename.replace("docker-compose-", "").replace(".yml", "")
                files.append(run_id)
        return files