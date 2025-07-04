"""Redis stream consumer for trading simulation data"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import redis.asyncio as redis
from redis.exceptions import ConnectionError, ResponseError

from ..core.config import get_config
from .database_service import DatabaseService

logger = logging.getLogger(__name__)

class RedisStreamConsumer:
    """Redis stream consumer for real-time trading data"""
    
    def __init__(self, database_service: DatabaseService):
        self.config = get_config()
        self.database_service = database_service
        self.redis_client: Optional[redis.Redis] = None
        self.consumer_group = "trading-api-group"
        self.consumer_name = "trading-api-consumer"
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
        """Connect to Redis and initialize consumer group"""
        try:
            self.redis_client = redis.Redis(
                host=self.config.database.redis_host,
                port=self.config.database.redis_port,
                decode_responses=True
            )
            
            # Test connection
            await self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {self.config.database.redis_host}:{self.config.database.redis_port}")
            
            # Verify or create consumer group
            if not await self._ensure_consumer_group():
                logger.error("❌ Failed to initialize consumer group")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            return False
    
    async def _ensure_consumer_group(self) -> bool:
        """Ensure consumer group exists and is properly configured"""
        try:
            stream_name = self.config.database.redis_stream_name
            
            # Check if stream exists
            try:
                await self.redis_client.xinfo_stream(stream_name)
                logger.debug(f"📊 Stream '{stream_name}' exists")
            except ResponseError as e:
                if "no such key" in str(e).lower():
                    logger.info(f"📊 Stream '{stream_name}' does not exist, will be created")
                else:
                    logger.error(f"❌ Error checking stream: {e}")
                    return False
            
            # Create consumer group if it doesn't exist
            try:
                await self.redis_client.xgroup_create(
                    stream_name,
                    self.consumer_group,
                    id="0",
                    mkstream=True
                )
                logger.info(f"✅ Created consumer group: {self.consumer_group}")
                
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.info(f"📊 Consumer group already exists: {self.consumer_group}")
                else:
                    logger.error(f"❌ Failed to create consumer group: {e}")
                    return False
            
            # Verify consumer group exists
            try:
                groups = await self.redis_client.xinfo_groups(stream_name)
                group_exists = any(group['name'] == self.consumer_group for group in groups)
                
                if group_exists:
                    logger.info(f"✅ Consumer group '{self.consumer_group}' verified")
                    return True
                else:
                    logger.error(f"❌ Consumer group '{self.consumer_group}' not found after creation")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Failed to verify consumer group: {e}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error ensuring consumer group: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("🔌 Disconnected from Redis")
    
    async def start_consuming(self):
        """Start consuming messages from Redis stream"""
        if not self.redis_client:
            logger.error("Redis client not connected")
            return
        
        self.running = True
        self.stats["start_time"] = datetime.now()
        logger.info(f"🚀 Starting Redis stream consumption from {self.config.database.redis_stream_name}")
        
        while self.running:
            try:
                # Read messages from the stream
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {self.config.database.redis_stream_name: ">"},
                    count=10,
                    block=1000  # Block for 1 second
                )
                
                if messages:
                    await self._process_messages(messages)
                    
            except ConnectionError as e:
                logger.error(f"💥 Redis connection lost: {e}")
                self.stats["last_error"] = f"Connection lost: {e}"
                await self._reconnect()
            except Exception as e:
                logger.error(f"❌ Error consuming messages: {e}")
                self.stats["last_error"] = f"Consumption error: {e}"
                await asyncio.sleep(1)
    
    async def stop_consuming(self):
        """Stop consuming messages"""
        self.running = False
        logger.info("🛑 Stopping Redis stream consumption")
    
    async def _process_messages(self, messages: List[tuple]):
        """Process messages from Redis stream"""
        for stream_name, stream_messages in messages:
            logger.info(f"📥 Processing {len(stream_messages)} messages from stream {stream_name}")
            
            for message_id, fields in stream_messages:
                message_processed = False
                self.stats["last_message_time"] = datetime.now()
                
                try:
                    logger.debug(f"🔄 Processing message {message_id}: {fields}")
                    await self._handle_message(message_id, fields)
                    message_processed = True
                    self.stats["messages_processed"] += 1
                    self.stats["database_write_success"] += 1
                    logger.debug(f"✅ Successfully processed message {message_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing message {message_id}: {e}")
                    logger.error(f"📋 Message fields: {fields}")
                    self.stats["messages_failed"] += 1
                    self.stats["database_write_failures"] += 1
                    self.stats["last_error"] = f"Message processing error: {e}"
                    # Don't acknowledge failed messages - they'll be retried
                    continue
                
                # Only acknowledge if message was successfully processed
                if message_processed:
                    try:
                        await self.redis_client.xack(
                            self.config.database.redis_stream_name,
                            self.consumer_group,
                            message_id
                        )
                        logger.debug(f"✅ Acknowledged message {message_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to acknowledge message {message_id}: {e}")
                        self.stats["last_error"] = f"Message acknowledgment error: {e}"
    
    async def _handle_message(self, message_id: str, fields: Dict[str, str]):
        """Handle individual message based on type"""
        message_type = fields.get("type")
        run_id = fields.get("run_id")
        data_str = fields.get("data")
        timestamp = fields.get("timestamp")
        
        if not all([message_type, run_id, data_str]):
            logger.warning(f"Incomplete message: {fields}")
            return
        
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON data: {e}")
            return
        
        logger.debug(f"📨 Processing {message_type} for run_id: {run_id}")
        
        if message_type == "live_stats":
            self.stats["message_types"]["live_stats"] += 1
            await self._process_live_stats(run_id, data, timestamp)
        elif message_type == "final_results":
            self.stats["message_types"]["final_results"] += 1
            await self._process_final_results(run_id, data, timestamp)
        elif message_type == "trade_event":
            self.stats["message_types"]["trade_event"] += 1
            await self._process_trade_event(run_id, data, timestamp)
        else:
            self.stats["message_types"]["unknown"] += 1
            logger.warning(f"Unknown message type: {message_type}")
    
    async def _process_live_stats(self, run_id: str, stats_data: Dict[str, Any], timestamp: str):
        """Process live statistics updates"""
        logger.info(f"📊 Processing live stats for run_id: {run_id}")
        logger.debug(f"📊 Live stats data: {stats_data}")
        
        try:
            # Update existing simulation run with live stats
            await self.database_service.update_simulation_live_stats(run_id, stats_data)
            logger.info(f"✅ Successfully updated live stats for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update live stats for {run_id}: {e}")
            logger.error(f"📋 Stats data: {stats_data}")
            raise  # Re-raise to prevent message acknowledgment
    
    async def _process_final_results(self, run_id: str, results_data: Dict[str, Any], timestamp: str):
        """Process final simulation results"""
        logger.info(f"🏁 Processing final results for run_id: {run_id}")
        logger.debug(f"🏁 Final results data: {results_data}")
        
        try:
            # Update simulation run with final results
            await self.database_service.update_simulation_final_results(run_id, results_data)
            logger.info(f"✅ Successfully processed final results for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to process final results for {run_id}: {e}")
            logger.error(f"📋 Results data: {results_data}")
            raise  # Re-raise to prevent message acknowledgment
    
    async def _process_trade_event(self, run_id: str, trade_data: Dict[str, Any], timestamp: str):
        """Process individual trade events"""
        logger.info(f"💱 Processing trade event for run_id: {run_id}")
        logger.debug(f"💱 Trade data: {trade_data}")
        
        try:
            # Store individual trade
            await self.database_service.store_trade_event(run_id, trade_data)
            logger.info(f"✅ Successfully stored trade event for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to store trade event for {run_id}: {e}")
            logger.error(f"📋 Trade data: {trade_data}")
            raise  # Re-raise to prevent message acknowledgment
    
    async def _reconnect(self):
        """Attempt to reconnect to Redis"""
        logger.info("🔄 Attempting to reconnect to Redis...")
        await asyncio.sleep(5)  # Wait before reconnecting
        
        try:
            await self.disconnect()
            if await self.connect():
                logger.info("✅ Reconnected to Redis successfully")
            else:
                logger.error("❌ Failed to reconnect to Redis")
        except Exception as e:
            logger.error(f"❌ Reconnection failed: {e}")
    
    async def get_stream_info(self) -> Dict[str, Any]:
        """Get information about the Redis stream"""
        if not self.redis_client:
            return {}
        
        try:
            stream_info = await self.redis_client.xinfo_stream(self.config.database.redis_stream_name)
            group_info = await self.redis_client.xinfo_groups(self.config.database.redis_stream_name)
            
            return {
                "stream_info": stream_info,
                "groups": group_info
            }
        except Exception as e:
            logger.error(f"Failed to get stream info: {e}")
            return {}
    
    def get_consumer_stats(self) -> Dict[str, Any]:
        """Get consumer statistics"""
        stats = self.stats.copy()
        
        # Add computed statistics
        if stats["start_time"]:
            uptime = datetime.now() - stats["start_time"]
            stats["uptime_seconds"] = uptime.total_seconds()
            stats["uptime_human"] = str(uptime)
            
            # Calculate rates
            if stats["uptime_seconds"] > 0:
                stats["messages_per_second"] = stats["messages_processed"] / stats["uptime_seconds"]
                stats["success_rate"] = (
                    stats["database_write_success"] / 
                    (stats["database_write_success"] + stats["database_write_failures"]) 
                    if (stats["database_write_success"] + stats["database_write_failures"]) > 0 else 0
                )
        
        stats["is_running"] = self.running
        stats["connected"] = self.redis_client is not None
        
        # Format timestamps
        if stats["last_message_time"]:
            stats["last_message_time"] = stats["last_message_time"].isoformat()
        if stats["start_time"]:
            stats["start_time"] = stats["start_time"].isoformat()
        
        return stats