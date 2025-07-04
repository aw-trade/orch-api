"""Redis stream initialization utility"""

import asyncio
import logging
from typing import Optional
import redis.asyncio as redis
from redis.exceptions import ConnectionError, ResponseError

from ..core.config import get_config

logger = logging.getLogger(__name__)

class RedisInitializer:
    """Initialize Redis streams and consumer groups"""
    
    def __init__(self):
        self.config = get_config()
        self.redis_client: Optional[redis.Redis] = None
        
    async def connect(self) -> bool:
        """Connect to Redis"""
        try:
            self.redis_client = redis.Redis(
                host=self.config.database.redis_host,
                port=self.config.database.redis_port,
                decode_responses=True
            )
            
            # Test connection
            await self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {self.config.database.redis_host}:{self.config.database.redis_port}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("🔌 Disconnected from Redis")
    
    async def initialize_streams(self) -> bool:
        """Initialize Redis streams and consumer groups"""
        if not self.redis_client:
            logger.error("Redis client not connected")
            return False
        
        try:
            stream_name = self.config.database.redis_stream_name
            consumer_group = "trading-api-group"
            
            # Check if stream exists
            try:
                stream_info = await self.redis_client.xinfo_stream(stream_name)
                logger.info(f"📊 Stream '{stream_name}' already exists with {stream_info['length']} messages")
            except ResponseError as e:
                if "no such key" in str(e).lower():
                    logger.info(f"📊 Stream '{stream_name}' does not exist, will be created with consumer group")
                else:
                    raise
            
            # Create consumer group (this will create the stream if it doesn't exist)
            try:
                await self.redis_client.xgroup_create(
                    stream_name,
                    consumer_group,
                    id="0",
                    mkstream=True
                )
                logger.info(f"✅ Created consumer group '{consumer_group}' for stream '{stream_name}'")
                
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.info(f"📊 Consumer group '{consumer_group}' already exists")
                else:
                    logger.error(f"❌ Failed to create consumer group: {e}")
                    return False
            
            # Verify setup
            await self._verify_setup()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Redis streams: {e}")
            return False
    
    async def _verify_setup(self):
        """Verify Redis stream and consumer group setup"""
        try:
            stream_name = self.config.database.redis_stream_name
            
            # Get stream info
            stream_info = await self.redis_client.xinfo_stream(stream_name)
            logger.info(f"📊 Stream '{stream_name}': {stream_info['length']} messages, {stream_info['groups']} groups")
            
            # Get consumer group info
            groups = await self.redis_client.xinfo_groups(stream_name)
            for group in groups:
                logger.info(f"👥 Consumer group '{group['name']}': {group['consumers']} consumers, {group['pending']} pending")
            
        except Exception as e:
            logger.warning(f"⚠️ Could not verify setup: {e}")
    
    async def add_test_message(self) -> bool:
        """Add a test message to verify stream functionality"""
        if not self.redis_client:
            return False
        
        try:
            stream_name = self.config.database.redis_stream_name
            
            # Add test message
            message_id = await self.redis_client.xadd(
                stream_name,
                {
                    "type": "test",
                    "run_id": "test-init",
                    "data": '{"message": "Redis stream initialized successfully"}',
                    "timestamp": "2024-01-01T00:00:00Z"
                }
            )
            
            logger.info(f"✅ Added test message with ID: {message_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to add test message: {e}")
            return False

async def initialize_redis():
    """Initialize Redis streams and consumer groups"""
    initializer = RedisInitializer()
    
    try:
        if not await initializer.connect():
            return False
        
        success = await initializer.initialize_streams()
        
        if success:
            await initializer.add_test_message()
        
        return success
        
    finally:
        await initializer.disconnect()

if __name__ == "__main__":
    # Run initialization
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        success = await initialize_redis()
        if success:
            print("✅ Redis initialization completed successfully")
        else:
            print("❌ Redis initialization failed")
            exit(1)
    
    asyncio.run(main())