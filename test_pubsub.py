#!/usr/bin/env python3
"""
Test script to simulate the updated trade simulator pub/sub publishing
and verify the orchestration API can receive the messages correctly.
"""

import asyncio
import json
import logging
import redis.asyncio as redis
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_trade_simulator_pubsub():
    """Test the trade simulator pub/sub implementation"""
    
    # Connect to Redis
    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    
    try:
        # Test connection
        await redis_client.ping()
        logger.info("✅ Connected to Redis")
        
        # Simulate the message format that our updated trade simulator would send
        test_messages = [
            {
                "type": "live_stats",
                "run_id": "sim_test_123",
                "data": {
                    "timestamp": int(datetime.now().timestamp()),
                    "runtime_seconds": 120,
                    "status": "running",
                    "signals": {
                        "received": 100,
                        "executed": 85,
                        "execution_rate": 85.0
                    },
                    "trades": {
                        "total": 20,
                        "winning": 12,
                        "losing": 8,
                        "win_rate": 60.0
                    },
                    "financials": {
                        "current_capital": 105000.0,
                        "initial_capital": 100000.0,
                        "total_pnl": 5200.0,
                        "total_fees": 200.0,
                        "net_pnl": 5000.0,
                        "return_pct": 5.0,
                        "max_drawdown": 2.5
                    }
                },
                "timestamp": int(datetime.now().timestamp())
            },
            {
                "type": "trade_event",
                "run_id": "sim_test_123",
                "data": {
                    "id": 1,
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": 100.0,
                    "price": 150.25,
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "confidence": 75.5,
                    "fees": 1.50,
                    "source_algo": "test-algo"
                },
                "timestamp": int(datetime.now().timestamp())
            },
            {
                "type": "final_results",
                "run_id": "sim_test_123",
                "data": {
                    "timestamp": int(datetime.now().timestamp()),
                    "status": "completed",
                    "total_trades": 25,
                    "winning_trades": 15,
                    "losing_trades": 10,
                    "win_rate": 60.0,
                    "final_capital": 107500.0,
                    "total_pnl": 7800.0,
                    "total_fees": 300.0,
                    "net_pnl": 7500.0,
                    "return_pct": 7.5,
                    "max_drawdown": 3.2
                },
                "timestamp": int(datetime.now().timestamp())
            }
        ]
        
        # Publish each test message
        for message in test_messages:
            message_str = json.dumps(message)
            subscribers = await redis_client.publish("trading-stats", message_str)
            logger.info(f"📤 Published {message['type']} message to {subscribers} subscribers")
            logger.info(f"   Message: {message_str[:100]}...")
            await asyncio.sleep(2)  # Wait between messages
        
        logger.info("✅ All test messages published successfully")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        await redis_client.close()

if __name__ == "__main__":
    asyncio.run(test_trade_simulator_pubsub())