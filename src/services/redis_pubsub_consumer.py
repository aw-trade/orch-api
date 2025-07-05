"""Redis Pub/Sub consumer for trading simulation data"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import redis.asyncio as redis
from redis.exceptions import ConnectionError

from ..core.config import get_config
from .database_service import DatabaseService

logger = logging.getLogger(__name__)

class RedisPubSubConsumer:
    """Redis Pub/Sub consumer for real-time trading data"""
    
    def __init__(self, database_service: DatabaseService):
        self.config = get_config()
        self.database_service = database_service
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.running = False
        
        # Consumer statistics
        self.stats = {
            "messages_processed": 0,
            "messages_failed": 0,
            "last_message_time": None,
            "database_write_success": 0,
            "database_write_failures": 0,
            "start_time": None,
            "last_error": None,
            "message_types": {
                "live_stats": 0,
                "final_results": 0,
                "trade_event": 0,
                "unknown": 0
            }
        }
        
    async def connect(self) -> bool:
        """Connect to Redis and initialize Pub/Sub"""
        try:
            self.redis_client = redis.Redis(
                host=self.config.database.redis_host,
                port=self.config.database.redis_port,
                decode_responses=True,
                socket_connect_timeout=self.config.database.redis_connection_timeout
            )
            
            # Test connection
            await self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {self.config.database.redis_host}:{self.config.database.redis_port}")
            
            # Initialize Pub/Sub
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe(self.config.database.redis_channel_name)
            logger.info(f"✅ Subscribed to channel: {self.config.database.redis_channel_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
            logger.info("🔌 Unsubscribed from Redis Pub/Sub")
            
        if self.redis_client:
            await self.redis_client.close()
            logger.info("🔌 Disconnected from Redis")
    
    async def start_consuming(self):
        """Start consuming messages from Redis Pub/Sub"""
        if not self.pubsub:
            logger.error("Redis Pub/Sub not initialized")
            return
        
        self.running = True
        self.stats["start_time"] = datetime.now()
        logger.info(f"🚀 Starting Redis Pub/Sub consumption from {self.config.database.redis_channel_name}")
        
        try:
            async for message in self.pubsub.listen():
                if not self.running:
                    break
                    
                # Skip subscription confirmation messages
                if message["type"] != "message":
                    continue
                
                try:
                    await self._process_message(message)
                    
                except ConnectionError as e:
                    logger.error(f"💥 Redis connection lost: {e}")
                    self.stats["last_error"] = f"Connection lost: {e}"
                    await self._reconnect()
                except Exception as e:
                    logger.error(f"❌ Error processing message: {e}")
                    self.stats["last_error"] = f"Message processing error: {e}"
                    
        except Exception as e:
            logger.error(f"❌ Error in message consumption loop: {e}")
            self.stats["last_error"] = f"Consumption loop error: {e}"
    
    async def stop_consuming(self):
        """Stop consuming messages"""
        self.running = False
        logger.info("🛑 Stopping Redis Pub/Sub consumption")
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process a single message from Redis Pub/Sub"""
        self.stats["last_message_time"] = datetime.now()
        
        try:
            # Parse JSON payload
            data = json.loads(message["data"])
            logger.debug(f"📨 Received message: {data}")
            
            # Extract message components
            message_type = data.get("type")
            run_id = data.get("run_id")
            message_data = data.get("data")
            timestamp = data.get("timestamp")
            
            if not all([message_type, run_id, message_data]):
                logger.warning(f"Incomplete message: {data}")
                self.stats["messages_failed"] += 1
                return
            
            logger.info(f"📨 Processing {message_type} for run_id: {run_id}")
            
            # Route message by type
            if message_type == "live_stats":
                self.stats["message_types"]["live_stats"] += 1
                await self._process_live_stats(run_id, message_data, timestamp)
            elif message_type == "final_results":
                self.stats["message_types"]["final_results"] += 1
                await self._process_final_results(run_id, message_data, timestamp)
            elif message_type == "trade_event":
                self.stats["message_types"]["trade_event"] += 1
                await self._process_trade_event(run_id, message_data, timestamp)
            else:
                self.stats["message_types"]["unknown"] += 1
                logger.warning(f"Unknown message type: {message_type}")
                self.stats["messages_failed"] += 1
                return
            
            self.stats["messages_processed"] += 1
            self.stats["database_write_success"] += 1
            logger.debug(f"✅ Successfully processed {message_type} for {run_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {e}")
            logger.error(f"Raw message: {message}")
            self.stats["messages_failed"] += 1
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}")
            logger.error(f"Message data: {message}")
            self.stats["messages_failed"] += 1
            self.stats["database_write_failures"] += 1
            self.stats["last_error"] = f"Message processing error: {e}"
    
    async def _process_live_stats(self, run_id: str, stats_data: Dict[str, Any], timestamp: str):
        """Process live statistics updates"""
        logger.info(f"📊 Processing live stats for run_id: {run_id}")
        
        try:
            await self.database_service.update_simulation_live_stats(run_id, stats_data)
            logger.info(f"✅ Successfully updated live stats for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update live stats for {run_id}: {e}")
            raise
    
    async def _process_final_results(self, run_id: str, results_data: Dict[str, Any], timestamp: str):
        """Process final simulation results"""
        logger.info(f"🏁 Processing final results for run_id: {run_id}")
        
        try:
            await self.database_service.update_simulation_final_results(run_id, results_data)
            logger.info(f"✅ Successfully processed final results for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to process final results for {run_id}: {e}")
            raise
    
    async def _process_trade_event(self, run_id: str, trade_data: Dict[str, Any], timestamp: str):
        """Process individual trade events"""
        logger.info(f"💱 Processing trade event for run_id: {run_id}")
        
        try:
            await self.database_service.store_trade_event(run_id, trade_data)
            logger.info(f"✅ Successfully processed trade event for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to process trade event for {run_id}: {e}")
            raise
    
    async def _reconnect(self):
        """Attempt to reconnect to Redis"""
        logger.info("🔄 Attempting to reconnect to Redis...")
        
        await asyncio.sleep(self.config.database.redis_reconnect_delay)
        
        try:
            await self.disconnect()
            if await self.connect():
                logger.info("✅ Successfully reconnected to Redis")
            else:
                logger.error("❌ Failed to reconnect to Redis")
        except Exception as e:
            logger.error(f"❌ Error during reconnection: {e}")
    
    def get_consumer_stats(self) -> Dict[str, Any]:
        """Get consumer statistics"""
        stats = self.stats.copy()
        stats["is_running"] = self.running
        stats["connected"] = self.redis_client is not None and self.pubsub is not None
        
        # Calculate derived stats
        if stats["messages_processed"] > 0:
            total_messages = stats["messages_processed"] + stats["messages_failed"]
            stats["success_rate"] = stats["messages_processed"] / total_messages
        else:
            stats["success_rate"] = 0
        
        # Calculate messages per second
        if stats["start_time"]:
            elapsed = (datetime.now() - stats["start_time"]).total_seconds()
            if elapsed > 0:
                stats["messages_per_second"] = stats["messages_processed"] / elapsed
            else:
                stats["messages_per_second"] = 0
        else:
            stats["messages_per_second"] = 0
        
        return stats
    
    async def get_channel_info(self) -> Dict[str, Any]:
        """Get Redis channel information"""
        if not self.redis_client:
            return {"error": "Not connected to Redis"}
        
        try:
            # Get number of subscribers for the channel
            pubsub_channels = await self.redis_client.pubsub_channels(self.config.database.redis_channel_name)
            num_subscribers = await self.redis_client.pubsub_numsub(self.config.database.redis_channel_name)
            
            return {
                "channel_name": self.config.database.redis_channel_name,
                "channel_exists": len(pubsub_channels) > 0,
                "subscribers": dict(num_subscribers),
                "connected": True
            }
        except Exception as e:
            return {"error": str(e)}