# Trading System Database Architecture

This document describes the persistent database setup for the trading simulation system.

## Architecture Overview

The database infrastructure is **completely decoupled** from the trading services:

```
┌─────────────────────────────────────────────────────────────┐
│                 Persistent Database Layer                   │
├─────────────────────────────┬───────────────────────────────┤
│        PostgreSQL          │           MongoDB             │
│    (Results & Analytics)    │    (Configurations & Meta)    │
│                             │                               │
│ - Simulation runs           │ - Algorithm configurations    │
│ - Trade history             │ - Simulator settings          │
│ - Positions                 │ - Version management          │
│ - Performance metrics       │ - Run metadata                │
└─────────────────────────────┴───────────────────────────────┘
                              ▲
                              │
         ┌────────────────────┼────────────────────┐
         │                   │                    │
   ┌──────────┐      ┌──────────────┐      ┌──────────┐
   │   API    │      │  Algorithm   │      │Simulator │
   │ Server   │      │  Container   │      │Container │
   └──────────┘      └──────────────┘      └──────────┘
```

## Quick Start

### 1. Setup Persistent Databases

```bash
# Start the persistent database infrastructure
./setup-databases.sh
```

This will:
- Create a dedicated Docker network for databases
- Start PostgreSQL and MongoDB with persistent volumes
- Initialize database schemas and default data
- Verify database connectivity

### 2. Start Trading Services

```bash
# Start the trading simulation services
docker compose up -d
```

The trading services will automatically connect to the persistent databases.

### 3. Verify Setup

```bash
# Check API health (includes database connectivity)
curl http://localhost:8000/health

# Check database status
docker compose -f docker-compose.databases.yml ps
```

## Database Services

### PostgreSQL (Results Database)
- **Container**: `trading-postgres`
- **Port**: `5432`
- **Database**: `trading_results`
- **User**: `trading_user`
- **Purpose**: Store simulation results, trades, positions, and analytics

**Tables**:
- `simulation_runs` - Main simulation records with performance metrics
- `trades` - Individual trade records
- `positions` - Final positions per simulation

### MongoDB (Configuration Database)
- **Container**: `trading-mongodb`
- **Port**: `27017`
- **Database**: `trading_configs`
- **User**: `admin`
- **Purpose**: Store algorithm configurations, versions, and metadata

**Collections**:
- `simulation_configs` - Run configurations and metadata
- `algorithm_versions` - Algorithm version definitions
- `simulator_configs` - Simulator configuration templates

## Data Persistence

### Volumes
- `trading_postgres_data` - PostgreSQL data directory
- `trading_mongodb_data` - MongoDB data directory
- `trading_mongodb_config` - MongoDB configuration
- `trading_pgadmin_data` - PgAdmin settings (if using admin tools)

### Backup Strategy

```bash
# Backup PostgreSQL
docker exec trading-postgres pg_dump -U trading_user trading_results > backup_postgres.sql

# Backup MongoDB
docker exec trading-mongodb mongodump --username admin --password admin_pass --authenticationDatabase admin --db trading_configs --out /tmp/backup
docker cp trading-mongodb:/tmp/backup ./backup_mongodb/
```

## Administration Tools (Optional)

Start admin tools for database management:

```bash
docker compose -f docker-compose.databases.yml --profile admin-tools up -d
```

**Access**:
- **PgAdmin**: http://localhost:5050
  - Email: `admin@trading.local`
  - Password: `admin123`
- **Mongo Express**: http://localhost:8081
  - Username: `admin`
  - Password: `admin123`

## Database Management

### Start Databases Only
```bash
docker compose -f docker-compose.databases.yml up -d
```

### Stop Databases (Data Persists)
```bash
docker compose -f docker-compose.databases.yml down
```

### Reset Databases (⚠️ Deletes All Data)
```bash
docker compose -f docker-compose.databases.yml down -v
docker volume rm trading_postgres_data trading_mongodb_data trading_mongodb_config
```

### View Database Logs
```bash
# PostgreSQL logs
docker logs trading-postgres

# MongoDB logs
docker logs trading-mongodb
```

## Environment Variables

The trading services use these environment variables to connect to databases:

### PostgreSQL
- `POSTGRES_HOST` - Database hostname
- `POSTGRES_PORT` - Database port (5432)
- `POSTGRES_DB` - Database name (trading_results)
- `POSTGRES_USER` - Username (trading_user)
- `POSTGRES_PASSWORD` - Password

### MongoDB
- `MONGODB_HOST` - Database hostname
- `MONGODB_PORT` - Database port (27017)
- `MONGODB_USERNAME` - Username (admin)
- `MONGODB_PASSWORD` - Password
- `MONGODB_DATABASE` - Database name (trading_configs)

## Network Architecture

### Database Network
- **Name**: `trading-db-network`
- **Purpose**: Isolated network for database communication
- **Containers**: `postgres`, `mongodb`, `pgadmin`, `mongo-express`

### Service Network
- **Name**: `trading-network`
- **Purpose**: Communication between trading services
- **External Connection**: Links to `trading-db-network` for database access

## Scaling Considerations

### Read Replicas
For production workloads, consider adding read replicas:

```yaml
postgres-replica:
  image: postgres:15
  environment:
    PGUSER: replicator
    POSTGRES_PASSWORD: replica_pass
    PGPASSWORD: replica_pass
  command: |
    bash -c "
    pg_basebackup -h postgres -D /var/lib/postgresql/data -U replicator -v -P -W
    echo 'standby_mode = on' >> /var/lib/postgresql/data/recovery.conf
    echo 'primary_conninfo = host=postgres port=5432 user=replicator' >> /var/lib/postgresql/data/recovery.conf
    postgres
    "
```

### MongoDB Replica Set
For high availability:

```yaml
mongodb-replica:
  image: mongo:7
  command: mongod --replSet rs0
  depends_on:
    - mongodb
```

## Security Notes

1. **Network Isolation**: Databases run on isolated Docker networks
2. **Password Management**: Use Docker secrets in production
3. **SSL/TLS**: Enable SSL for production deployments
4. **Firewall**: Only expose necessary ports
5. **Backups**: Implement automated backup strategies

## Troubleshooting

### Database Connection Issues
```bash
# Test PostgreSQL connection
docker exec trading-postgres psql -U trading_user -d trading_results -c "SELECT version();"

# Test MongoDB connection
docker exec trading-mongodb mongosh --username admin --password admin_pass --eval "db.adminCommand('ping')"
```

### Performance Monitoring
```bash
# PostgreSQL performance
docker exec trading-postgres psql -U trading_user -d trading_results -c "SELECT * FROM pg_stat_activity;"

# MongoDB performance
docker exec trading-mongodb mongosh --username admin --password admin_pass --eval "db.adminCommand('serverStatus')"
```

### Common Issues

1. **Port Conflicts**: Ensure ports 5432 and 27017 are available
2. **Volume Permissions**: Check Docker volume permissions
3. **Memory Limits**: Ensure sufficient memory for database containers
4. **Network Connectivity**: Verify Docker network configuration