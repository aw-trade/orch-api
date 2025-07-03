from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import logging
from .models import SimulationConfigDocument, AlgorithmVersionDocument, SimulationStatus

logger = logging.getLogger(__name__)

class MongoDBClient:
    def __init__(self):
        self.client = None
        self.database = None
        self.host = os.getenv("MONGODB_HOST", "localhost")
        self.port = int(os.getenv("MONGODB_PORT", "27017"))
        self.username = os.getenv("MONGODB_USERNAME", "admin")
        self.password = os.getenv("MONGODB_PASSWORD", "admin_pass")
        self.db_name = os.getenv("MONGODB_DATABASE", "trading_configs")

    async def connect(self):
        """Initialize MongoDB connection"""
        try:
            connection_string = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}"
            self.client = AsyncIOMotorClient(connection_string)
            self.database = self.client[self.db_name]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB at {self.host}:{self.port}")
            
            # Create indexes
            await self._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    async def disconnect(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")

    async def _create_indexes(self):
        """Create database indexes for better performance"""
        try:
            # Indexes for simulation_configs collection
            configs_collection = self.database.simulation_configs
            await configs_collection.create_index("run_id", unique=True)
            await configs_collection.create_index("status")
            await configs_collection.create_index("created_at")
            await configs_collection.create_index("algorithm_version")
            
            # Indexes for algorithm_versions collection
            versions_collection = self.database.algorithm_versions
            await versions_collection.create_index("version", unique=True)
            await versions_collection.create_index("created_at")
            
            logger.info("Created MongoDB indexes")
        except Exception as e:
            logger.error(f"Failed to create MongoDB indexes: {e}")

    async def save_simulation_config(self, config: SimulationConfigDocument) -> bool:
        """Save simulation configuration"""
        try:
            collection = self.database.simulation_configs
            doc = config.dict()
            doc["_id"] = config.run_id  # Use run_id as document ID
            
            await collection.insert_one(doc)
            logger.info(f"Saved simulation config: {config.run_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save simulation config {config.run_id}: {e}")
            return False

    async def update_simulation_config(self, run_id: str, updates: Dict[str, Any]) -> bool:
        """Update simulation configuration"""
        try:
            collection = self.database.simulation_configs
            result = await collection.update_one(
                {"_id": run_id},
                {"$set": updates}
            )
            
            if result.modified_count > 0:
                logger.info(f"Updated simulation config: {run_id}")
                return True
            else:
                logger.warning(f"No simulation config found to update: {run_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to update simulation config {run_id}: {e}")
            return False

    async def get_simulation_config(self, run_id: str) -> Optional[SimulationConfigDocument]:
        """Get simulation configuration by run ID"""
        try:
            collection = self.database.simulation_configs
            doc = await collection.find_one({"_id": run_id})
            
            if doc:
                # Remove MongoDB's _id field and replace with run_id
                doc.pop("_id", None)
                return SimulationConfigDocument(**doc)
            return None
        except Exception as e:
            logger.error(f"Failed to get simulation config {run_id}: {e}")
            return None

    async def list_simulation_configs(self, 
                                    limit: int = 100, 
                                    offset: int = 0,
                                    status: Optional[SimulationStatus] = None,
                                    algorithm_version: Optional[str] = None) -> List[SimulationConfigDocument]:
        """List simulation configurations with filtering"""
        try:
            collection = self.database.simulation_configs
            
            # Build filter query
            filter_query = {}
            if status:
                filter_query["status"] = status.value
            if algorithm_version:
                filter_query["algorithm_version"] = algorithm_version

            # Execute query with pagination
            cursor = collection.find(filter_query).sort("created_at", -1).skip(offset).limit(limit)
            docs = await cursor.to_list(length=limit)
            
            # Convert to Pydantic models
            configs = []
            for doc in docs:
                doc.pop("_id", None)  # Remove MongoDB's _id field
                configs.append(SimulationConfigDocument(**doc))
            
            return configs
        except Exception as e:
            logger.error(f"Failed to list simulation configs: {e}")
            return []

    async def save_algorithm_version(self, version_doc: AlgorithmVersionDocument) -> bool:
        """Save algorithm version information"""
        try:
            collection = self.database.algorithm_versions
            doc = version_doc.dict()
            doc["_id"] = version_doc.version  # Use version as document ID
            
            await collection.replace_one(
                {"_id": version_doc.version},
                doc,
                upsert=True
            )
            logger.info(f"Saved algorithm version: {version_doc.version}")
            return True
        except Exception as e:
            logger.error(f"Failed to save algorithm version {version_doc.version}: {e}")
            return False

    async def get_algorithm_version(self, version: str) -> Optional[AlgorithmVersionDocument]:
        """Get algorithm version by version string"""
        try:
            collection = self.database.algorithm_versions
            doc = await collection.find_one({"_id": version})
            
            if doc:
                doc.pop("_id", None)
                return AlgorithmVersionDocument(**doc)
            return None
        except Exception as e:
            logger.error(f"Failed to get algorithm version {version}: {e}")
            return None

    async def list_algorithm_versions(self) -> List[AlgorithmVersionDocument]:
        """List all algorithm versions"""
        try:
            collection = self.database.algorithm_versions
            cursor = collection.find({}).sort("created_at", -1)
            docs = await cursor.to_list(length=None)
            
            versions = []
            for doc in docs:
                doc.pop("_id", None)
                versions.append(AlgorithmVersionDocument(**doc))
            
            return versions
        except Exception as e:
            logger.error(f"Failed to list algorithm versions: {e}")
            return []

    async def get_config_stats(self) -> Dict[str, Any]:
        """Get statistics about stored configurations"""
        try:
            collection = self.database.simulation_configs
            
            # Aggregate statistics
            pipeline = [
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            status_stats = {}
            async for doc in collection.aggregate(pipeline):
                status_stats[doc["_id"]] = doc["count"]
            
            # Get total count and algorithm version distribution
            total_count = await collection.count_documents({})
            
            version_pipeline = [
                {
                    "$group": {
                        "_id": "$algorithm_version",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            version_stats = {}
            async for doc in collection.aggregate(version_pipeline):
                version_stats[doc["_id"]] = doc["count"]
            
            return {
                "total_configurations": total_count,
                "status_distribution": status_stats,
                "algorithm_versions": version_stats
            }
        except Exception as e:
            logger.error(f"Failed to get config stats: {e}")
            return {}

    async def search_configs(self, 
                           search_query: str, 
                           limit: int = 50) -> List[SimulationConfigDocument]:
        """Search configurations by run_id or metadata"""
        try:
            collection = self.database.simulation_configs
            
            # Create text search query
            filter_query = {
                "$or": [
                    {"run_id": {"$regex": search_query, "$options": "i"}},
                    {"metadata.notes": {"$regex": search_query, "$options": "i"}},
                    {"metadata.started_by": {"$regex": search_query, "$options": "i"}}
                ]
            }
            
            cursor = collection.find(filter_query).sort("created_at", -1).limit(limit)
            docs = await cursor.to_list(length=limit)
            
            configs = []
            for doc in docs:
                doc.pop("_id", None)
                configs.append(SimulationConfigDocument(**doc))
            
            return configs
        except Exception as e:
            logger.error(f"Failed to search configs: {e}")
            return []

# Global client instance
mongodb_client = MongoDBClient()