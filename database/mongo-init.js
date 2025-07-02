// MongoDB initialization script for trading configurations database

// Switch to the trading_configs database
db = db.getSiblingDB('trading_configs');

// Create a user for the trading application
db.createUser({
  user: 'trading_app',
  pwd: 'trading_app_pass',
  roles: [
    {
      role: 'readWrite',
      db: 'trading_configs'
    }
  ]
});

// Create collections with validation schemas
db.createCollection('simulation_configs', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['run_id', 'created_at', 'status', 'duration_seconds', 'algorithm_version', 'algo_config', 'simulator_config'],
      properties: {
        run_id: {
          bsonType: 'string',
          description: 'Unique identifier for the simulation run'
        },
        created_at: {
          bsonType: 'date',
          description: 'Creation timestamp'
        },
        status: {
          bsonType: 'string',
          enum: ['pending', 'running', 'completed', 'failed', 'stopped'],
          description: 'Current status of the simulation'
        },
        duration_seconds: {
          bsonType: 'int',
          minimum: 1,
          description: 'Duration of the simulation in seconds'
        },
        algorithm_version: {
          bsonType: 'string',
          description: 'Version of the algorithm being used'
        },
        algo_config: {
          bsonType: 'object',
          description: 'Algorithm configuration parameters'
        },
        simulator_config: {
          bsonType: 'object',
          description: 'Simulator configuration parameters'
        },
        metadata: {
          bsonType: 'object',
          description: 'Additional metadata for the simulation'
        }
      }
    }
  }
});

db.createCollection('algorithm_versions', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['version', 'created_at', 'description', 'default_config'],
      properties: {
        version: {
          bsonType: 'string',
          description: 'Algorithm version identifier'
        },
        created_at: {
          bsonType: 'date',
          description: 'Creation timestamp'
        },
        description: {
          bsonType: 'string',
          description: 'Description of the algorithm version'
        },
        default_config: {
          bsonType: 'object',
          description: 'Default configuration for this algorithm version'
        },
        config_schema: {
          bsonType: 'object',
          description: 'Configuration validation schema'
        }
      }
    }
  }
});

// Create indexes for better performance
db.simulation_configs.createIndex({ "run_id": 1 }, { unique: true });
db.simulation_configs.createIndex({ "status": 1 });
db.simulation_configs.createIndex({ "created_at": -1 });
db.simulation_configs.createIndex({ "algorithm_version": 1 });
db.simulation_configs.createIndex({ "metadata.started_by": 1 });

db.algorithm_versions.createIndex({ "version": 1 }, { unique: true });
db.algorithm_versions.createIndex({ "created_at": -1 });

// Insert default algorithm version
db.algorithm_versions.insertOne({
  version: "v1.0.0",
  created_at: new Date(),
  description: "Initial order-book imbalance algorithm",
  default_config: {
    IMBALANCE_THRESHOLD: 0.6,
    MIN_VOLUME_THRESHOLD: 10.0,
    LOOKBACK_PERIODS: 5,
    SIGNAL_COOLDOWN_MS: 100
  },
  config_schema: {
    IMBALANCE_THRESHOLD: { type: "number", minimum: 0.1, maximum: 1.0 },
    MIN_VOLUME_THRESHOLD: { type: "number", minimum: 1.0, maximum: 1000.0 },
    LOOKBACK_PERIODS: { type: "integer", minimum: 1, maximum: 20 },
    SIGNAL_COOLDOWN_MS: { type: "integer", minimum: 10, maximum: 10000 }
  }
});

// Insert sample simulator configuration template
db.simulator_configs.insertOne({
  _id: "default_simulator_config",
  version: "v1.0.0",
  created_at: new Date(),
  description: "Default simulator configuration",
  config: {
    INITIAL_CAPITAL: 100000.0,
    POSITION_SIZE_PCT: 0.05,
    MAX_POSITION_SIZE: 10000.0,
    TRADING_FEE_PCT: 0.001,
    MIN_CONFIDENCE: 0.3,
    ENABLE_SHORTING: true,
    STATS_INTERVAL_SECS: 30,
    AUTO_REGISTER: true
  }
});

print("MongoDB initialization completed successfully!");
print("Created collections: simulation_configs, algorithm_versions");
print("Created indexes for performance optimization");
print("Inserted default algorithm version v1.0.0");