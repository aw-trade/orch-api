# Trading Simulator Orchestration API

A FastAPI-based orchestration system for managing trading algorithm simulations with persistent storage and real-time monitoring.

## Project Structure

```
orch-api/
├── src/                          # Source code
│   ├── api/                      # API application
│   │   ├── main.py              # FastAPI application setup
│   │   └── endpoints/           # API endpoint modules
│   │       ├── simulation.py   # Simulation management endpoints
│   │       ├── results.py      # Results retrieval endpoints
│   │       ├── analytics.py    # Analytics endpoints
│   │       └── resources.py    # Resource management endpoints
│   ├── services/                # Business logic services
│   │   ├── simulator_service.py # Simulation orchestration
│   │   └── resource_manager.py  # Docker resource management
│   ├── database/                # Database layer
│   │   ├── models.py           # Pydantic models
│   │   ├── postgres_client.py  # PostgreSQL client
│   │   ├── mongodb_client.py   # MongoDB client
│   │   └── schemas/            # Database schemas
│   │       ├── init.sql        # PostgreSQL schema
│   │       └── mongo-init.js   # MongoDB initialization
│   ├── core/                   # Core configuration
│   │   └── config.py          # Application configuration
│   └── utils/                  # Utility modules
│       └── compose_generator.py # Docker Compose generation
├── tests/                      # Test suite
│   ├── unit/                  # Unit tests
│   ├── integration/           # Integration tests
│   ├── test_api_simple.py     # Simple API tests
│   ├── test_parallel_simulations.py
│   └── test_results_simple.py
├── docker/                     # Docker configuration
│   ├── docker-compose.yml     # Main compose file
│   ├── docker-compose.databases.yml # Database services
│   ├── compose_files/         # Generated compose files
│   └── scripts/               # Setup scripts
│       └── setup-databases.sh
├── docs/                       # Documentation
│   ├── README.md             # Main documentation
│   └── README-databases.md   # Database documentation
├── data/                       # Data directory
│   └── backup/               # Backup files
├── main.py                     # Entry point
└── requirements.txt           # Python dependencies
```

## Running the Application

### Using Python directly:
```bash
python main.py
```

### Using Docker:
```bash
# Start databases
docker-compose -f docker/docker-compose.databases.yml up -d

# Start the application
docker-compose -f docker/docker-compose.yml up -d
```

## API Documentation

Once running, visit `http://localhost:8000/docs` for interactive API documentation.

## Key Features

- **Modular Architecture**: Clean separation of concerns with organized modules
- **Dual Database Support**: PostgreSQL for structured data, MongoDB for configurations
- **Real-time Monitoring**: Live stats collection during simulations
- **Resource Management**: Docker container lifecycle management
- **Comprehensive Testing**: Unit and integration test suites
- **Configuration Management**: Environment-based configuration system

## Development

### Adding New Endpoints

1. Create endpoint module in `src/api/endpoints/`
2. Import and include router in `src/api/main.py`
3. Add corresponding tests in `tests/`

### Database Migrations

- PostgreSQL schemas: `src/database/schemas/init.sql`
- MongoDB initialization: `src/database/schemas/mongo-init.js`

### Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_api_simple.py
```