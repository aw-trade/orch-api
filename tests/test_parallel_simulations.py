#!/usr/bin/env python3
"""
Test script for parallel simulation functionality
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

BASE_URL = "http://localhost:8000"

class SimulationTester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def start_simulation(self, run_suffix: str, duration: int = 30) -> Dict:
        """Start a simulation with a custom run suffix"""
        payload = {
            "duration_seconds": duration,
            "algorithm_version": f"test-v1-{run_suffix}",
            "metadata": {"test_run": True, "suffix": run_suffix}
        }
        
        async with self.session.post(f"{self.base_url}/simulate/start", json=payload) as resp:
            result = await resp.json()
            print(f"Started simulation {run_suffix}: {result}")
            return result
    
    async def get_status(self, run_id: Optional[str] = None) -> Dict:
        """Get simulation status"""
        url = f"{self.base_url}/simulate/status"
        if run_id:
            url += f"/{run_id}"
        
        async with self.session.get(url) as resp:
            return await resp.json()
    
    async def stop_simulation(self, run_id: str) -> Dict:
        """Stop a specific simulation"""
        async with self.session.post(f"{self.base_url}/simulate/stop/{run_id}") as resp:
            return await resp.json()
    
    async def get_resource_usage(self) -> Dict:
        """Get resource usage"""
        async with self.session.get(f"{self.base_url}/resources/usage") as resp:
            return await resp.json()
    
    async def cleanup_resources(self) -> Dict:
        """Cleanup orphaned resources"""
        async with self.session.post(f"{self.base_url}/resources/cleanup") as resp:
            return await resp.json()

async def test_sequential_simulations():
    """Test that multiple simulations can be started and stopped sequentially"""
    print("\\n=== Testing Sequential Simulations ===")
    
    async with SimulationTester() as tester:
        run_ids = []
        
        # Start 3 simulations sequentially
        for i in range(3):
            result = await tester.start_simulation(f"seq-{i}", duration=60)
            if result.get("success"):
                run_ids.append(result["run_id"])
            await asyncio.sleep(1)  # Small delay between starts
        
        print(f"Started {len(run_ids)} simulations: {run_ids}")
        
        # Check overall status
        status = await tester.get_status()
        print(f"Overall status: {json.dumps(status, indent=2)}")
        
        # Check individual statuses
        for run_id in run_ids:
            individual_status = await tester.get_status(run_id)
            print(f"Status for {run_id}: {individual_status['status']}")
        
        # Stop all simulations
        for run_id in run_ids:
            stop_result = await tester.stop_simulation(run_id)
            print(f"Stopped {run_id}: {stop_result.get('success', False)}")
        
        return len(run_ids)

async def test_parallel_simulation_starts():
    """Test starting multiple simulations in parallel"""
    print("\\n=== Testing Parallel Simulation Starts ===")
    
    async with SimulationTester() as tester:
        # Start 5 simulations in parallel
        tasks = []
        for i in range(5):
            task = tester.start_simulation(f"parallel-{i}", duration=45)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        run_ids = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Simulation parallel-{i} failed: {result}")
            elif result.get("success"):
                run_ids.append(result["run_id"])
                print(f"Simulation parallel-{i} started: {result['run_id']}")
            else:
                print(f"Simulation parallel-{i} failed to start: {result}")
        
        print(f"Successfully started {len(run_ids)} parallel simulations")
        
        # Wait a bit and check status
        await asyncio.sleep(5)
        status = await tester.get_status()
        print(f"Running simulations: {status.get('running_count', 0)}")
        
        # Stop all running simulations
        for run_id in run_ids:
            await tester.stop_simulation(run_id)
        
        return len(run_ids)

async def test_resource_management():
    """Test resource management functionality"""
    print("\\n=== Testing Resource Management ===")
    
    async with SimulationTester() as tester:
        # Get initial resource usage
        initial_usage = await tester.get_resource_usage()
        print(f"Initial resource usage: {json.dumps(initial_usage, indent=2)}")
        
        # Start a few simulations
        run_ids = []
        for i in range(3):
            result = await tester.start_simulation(f"resource-test-{i}", duration=30)
            if result.get("success"):
                run_ids.append(result["run_id"])
        
        # Check resource usage after starting
        usage_after_start = await tester.get_resource_usage()
        print(f"Resource usage after starting {len(run_ids)} simulations:")
        print(json.dumps(usage_after_start, indent=2))
        
        # Stop all simulations
        for run_id in run_ids:
            await tester.stop_simulation(run_id)
        
        # Wait a bit for cleanup
        await asyncio.sleep(2)
        
        # Run cleanup
        cleanup_result = await tester.cleanup_resources()
        print(f"Cleanup result: {json.dumps(cleanup_result, indent=2)}")
        
        # Check final resource usage
        final_usage = await tester.get_resource_usage()
        print(f"Final resource usage: {json.dumps(final_usage, indent=2)}")

async def test_simulation_lifecycle():
    """Test complete simulation lifecycle"""
    print("\\n=== Testing Complete Simulation Lifecycle ===")
    
    async with SimulationTester() as tester:
        # Start a simulation
        result = await tester.start_simulation("lifecycle-test", duration=20)
        if not result.get("success"):
            print("Failed to start lifecycle test simulation")
            return False
        
        run_id = result["run_id"]
        print(f"Started lifecycle test simulation: {run_id}")
        
        # Monitor the simulation for a few seconds
        for i in range(5):
            status = await tester.get_status(run_id)
            print(f"Lifecycle test status (t+{i*3}s): {status['status']}")
            await asyncio.sleep(3)
        
        # Stop the simulation
        stop_result = await tester.stop_simulation(run_id)
        print(f"Stopped lifecycle test: {stop_result.get('success', False)}")
        
        return True

async def main():
    """Run all tests"""
    print("Starting parallel simulation tests...")
    print(f"Testing against: {BASE_URL}")
    
    try:
        # Test sequential simulations
        seq_count = await test_sequential_simulations()
        
        # Test parallel starts
        parallel_count = await test_parallel_simulation_starts()
        
        # Test resource management
        await test_resource_management()
        
        # Test simulation lifecycle
        await test_simulation_lifecycle()
        
        print("\\n=== Test Summary ===")
        print(f"Sequential simulations tested: {seq_count}")
        print(f"Parallel simulations tested: {parallel_count}")
        print("All tests completed successfully!")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())