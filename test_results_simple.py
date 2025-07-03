#!/usr/bin/env python3
"""
Simple test to verify trade-simulator results collection and PostgreSQL logging
"""
import requests
import json
import time
import asyncio
import asyncpg
import os
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"
POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "trading_results"),
    "user": os.getenv("POSTGRES_USER", "trading_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "trading_pass")
}

class DatabaseChecker:
    """Helper to check database contents"""
    
    def __init__(self):
        self.conn = None
    
    async def connect(self):
        """Connect to PostgreSQL"""
        try:
            self.conn = await asyncpg.connect(**POSTGRES_CONFIG)
            print("✅ Connected to PostgreSQL")
        except Exception as e:
            print(f"❌ Failed to connect to PostgreSQL: {e}")
            return False
        return True
    
    async def get_simulation_run(self, run_id: str):
        """Get simulation run details from database"""
        if not self.conn:
            return None
            
        query = """
        SELECT * FROM simulation_runs 
        WHERE run_id = $1
        """
        try:
            result = await self.conn.fetchrow(query, run_id)
            return dict(result) if result else None
        except Exception as e:
            print(f"❌ Error querying simulation run: {e}")
            return None
    
    async def get_trades_count(self, run_id: str):
        """Get number of trades for a simulation"""
        if not self.conn:
            return 0
            
        query = "SELECT COUNT(*) FROM trades WHERE run_id = $1"
        try:
            result = await self.conn.fetchval(query, run_id)
            return result or 0
        except Exception as e:
            print(f"❌ Error counting trades: {e}")
            return 0
    
    async def get_positions_count(self, run_id: str):
        """Get number of positions for a simulation"""
        if not self.conn:
            return 0
            
        query = "SELECT COUNT(*) FROM positions WHERE run_id = $1"
        try:
            result = await self.conn.fetchval(query, run_id)
            return result or 0
        except Exception as e:
            print(f"❌ Error counting positions: {e}")
            return 0
    
    async def close(self):
        """Close database connection"""
        if self.conn:
            await self.conn.close()

def test_api_health():
    """Check if API is running"""
    print("🔍 Checking API health...")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API is healthy")
            return True
        else:
            print(f"❌ API health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ API not reachable: {e}")
        return False

def start_test_simulation():
    """Start a short simulation for testing"""
    print("\n🚀 Starting test simulation...")
    
    request_data = {
        "duration_seconds": 15,  # Short test duration
        "algo_consts": {
            "IMBALANCE_THRESHOLD": 0.7,
            "MIN_VOLUME_THRESHOLD": 10.0,
            "LOOKBACK_PERIODS": 5,
            "SIGNAL_COOLDOWN_MS": 100
        },
        "simulator_consts": {
            "INITIAL_CAPITAL": 10000.0,
            "POSITION_SIZE_PCT": 0.05,
            "TRADING_FEE_PCT": 0.001,
            "MIN_CONFIDENCE": 0.3,
            "ENABLE_SHORTING": True,
            "STATS_INTERVAL_SECS": 5,
            "AUTO_REGISTER": True
        }
    }
    
    try:
        response = requests.post(f"{API_BASE_URL}/simulate/start", json=request_data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            run_id = result.get("run_id")
            print(f"✅ Simulation started: {run_id}")
            return run_id
        else:
            print(f"❌ Failed to start simulation: {response.status_code}")
            if response.status_code != 500:
                print(f"Error: {response.json()}")
            return None
    except Exception as e:
        print(f"❌ Error starting simulation: {e}")
        return None

def wait_for_completion(run_id: str, max_wait_seconds: int = 30):
    """Wait for simulation to complete"""
    print(f"\n⏳ Waiting for simulation {run_id} to complete...")
    
    start_time = time.time()
    while (time.time() - start_time) < max_wait_seconds:
        try:
            response = requests.get(f"{API_BASE_URL}/simulate/status/{run_id}")
            if response.status_code == 200:
                status = response.json()
                current_status = status.get("status")
                remaining = status.get("remaining_seconds", 0)
                
                print(f"Status: {current_status}, Remaining: {remaining}s")
                
                if current_status in ["completed", "stopped", "failed"]:
                    print(f"✅ Simulation {current_status}")
                    return True
                    
            time.sleep(2)
        except Exception as e:
            print(f"❌ Error checking status: {e}")
            break
    
    print("⚠️ Simulation did not complete in time, stopping manually...")
    try:
        requests.post(f"{API_BASE_URL}/simulate/stop/{run_id}")
        time.sleep(3)  # Give it time to collect results
        return True
    except:
        return False

async def verify_database_results(run_id: str):
    """Check if results were properly stored in database"""
    print(f"\n🔍 Checking database for results of {run_id}...")
    
    db_checker = DatabaseChecker()
    if not await db_checker.connect():
        return False
    
    try:
        # Get simulation run details
        sim_run = await db_checker.get_simulation_run(run_id)
        if not sim_run:
            print(f"❌ No simulation run found in database for {run_id}")
            return False
        
        print("✅ Simulation run found in database")
        print(f"   Status: {sim_run.get('status')}")
        print(f"   Start time: {sim_run.get('start_time')}")
        print(f"   End time: {sim_run.get('end_time')}")
        print(f"   Duration: {sim_run.get('duration_seconds')}s")
        
        # Check key financial metrics
        print("\n📊 Financial Results:")
        print(f"   Initial Capital: ${sim_run.get('initial_capital', 0) or 0:,.2f}")
        print(f"   Final Capital: ${sim_run.get('final_capital', 0) or 0:,.2f}")
        print(f"   Total P&L: ${sim_run.get('total_pnl', 0) or 0:,.2f}")
        print(f"   Net P&L: ${sim_run.get('net_pnl', 0) or 0:,.2f}")
        print(f"   Return %: {sim_run.get('return_pct', 0) or 0:.2f}%")
        print(f"   Max Drawdown: {sim_run.get('max_drawdown', 0) or 0:.2f}%")
        
        # Check trading metrics
        print("\n📈 Trading Metrics:")
        print(f"   Total Trades: {sim_run.get('total_trades', 0) or 0}")
        print(f"   Winning Trades: {sim_run.get('winning_trades', 0) or 0}")
        print(f"   Losing Trades: {sim_run.get('losing_trades', 0) or 0}")
        print(f"   Win Rate: {sim_run.get('win_rate', 0) or 0:.2f}%")
        print(f"   Signals Received: {sim_run.get('signals_received', 0) or 0}")
        print(f"   Signals Executed: {sim_run.get('signals_executed', 0) or 0}")
        print(f"   Execution Rate: {sim_run.get('execution_rate', 0) or 0:.2f}%")
        
        # Check if we have detailed data
        trades_count = await db_checker.get_trades_count(run_id)
        positions_count = await db_checker.get_positions_count(run_id)
        
        print(f"\n💾 Detailed Data:")
        print(f"   Trades in DB: {trades_count}")
        print(f"   Positions in DB: {positions_count}")
        
        # Verify key fields are populated (indicating successful result collection)
        has_results = (
            sim_run.get('final_capital') is not None and
            sim_run.get('status') in ['COMPLETED', 'STOPPED'] and
            sim_run.get('end_time') is not None
        )
        
        if has_results:
            print("✅ Results successfully collected and stored!")
            return True
        else:
            print("❌ Results appear incomplete - may not have been collected properly")
            return False
            
    finally:
        await db_checker.close()

async def main():
    """Run the complete test"""
    print("🧪 Testing Trade-Simulator Results Collection & PostgreSQL Logging")
    print("=" * 70)
    
    # Step 1: Check API health
    if not test_api_health():
        print("\n❌ Test failed: API not available")
        return
    
    # Step 2: Start simulation
    run_id = start_test_simulation()
    if not run_id:
        print("\n❌ Test failed: Could not start simulation")
        return
    
    # Step 3: Wait for completion
    if not wait_for_completion(run_id):
        print("\n❌ Test failed: Simulation did not complete properly")
        return
    
    # Step 4: Verify database results
    success = await verify_database_results(run_id)
    
    # Summary
    print("\n" + "=" * 70)
    if success:
        print("🎉 TEST PASSED: Results collection and database logging working!")
        print(f"📋 Test simulation ID: {run_id}")
    else:
        print("❌ TEST FAILED: Results were not properly collected/stored")
    
    print("\nTo manually verify:")
    print(f"1. Check API logs for result collection messages")
    print(f"2. Query database: SELECT * FROM simulation_runs WHERE run_id = '{run_id}';")
    print(f"3. View results via API: GET {API_BASE_URL}/results/{run_id}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")