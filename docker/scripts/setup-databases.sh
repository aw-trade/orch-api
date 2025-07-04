#!/bin/bash

# Setup script for persistent trading databases
# This script sets up PostgreSQL and MongoDB as persistent services

set -e

echo "🗄️  Setting up persistent trading databases..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Clean up any existing network conflicts and create fresh network
echo "📡 Setting up database network..."
docker network rm trading-db-network 2>/dev/null || true
docker network create trading-db-network

# Start databases
echo "🚀 Starting PostgreSQL and MongoDB..."
docker compose -f docker-compose.databases.yml up -d

# Wait for databases to be healthy
echo "⏳ Waiting for databases to be ready..."

# Wait for PostgreSQL
echo "   Waiting for PostgreSQL..."
timeout 60 bash -c 'until docker exec trading-postgres pg_isready -U trading_user -d trading_results; do sleep 2; done'

# Wait for MongoDB
echo "   Waiting for MongoDB..."
timeout 60 bash -c 'until docker exec trading-mongodb mongosh --quiet --eval "db.adminCommand(\"ping\")" > /dev/null 2>&1; do sleep 2; done'

# Wait for Redis
echo "   Waiting for Redis..."
timeout 60 bash -c 'until docker exec trading-redis redis-cli ping > /dev/null 2>&1; do sleep 2; done'

echo "✅ Databases are ready!"

# Initialize Redis streams
echo "🔄 Initializing Redis streams..."
if docker exec trading-redis redis-cli ping > /dev/null 2>&1; then
    echo "📊 Setting up Redis streams and consumer groups..."
    docker exec trading-redis redis-cli XGROUP CREATE trading-stats trading-api-group 0 MKSTREAM 2>/dev/null || \
    echo "📊 Consumer group 'trading-api-group' already exists or was created"
    
    # Add test message to verify stream functionality
    TEST_MSG_ID=$(docker exec trading-redis redis-cli XADD trading-stats "*" \
        "type" "test" \
        "run_id" "setup-test" \
        "data" '{"message": "Redis stream initialized via setup script"}' \
        "timestamp" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
    
    echo "✅ Redis stream initialized with test message ID: $TEST_MSG_ID"
else
    echo "⚠️  Redis is not available for stream initialization"
fi

# Show database status
echo "📊 Database Status:"
echo "   PostgreSQL: $(docker exec trading-postgres pg_isready -U trading_user -d trading_results)"
echo "   MongoDB: $(docker exec trading-mongodb mongosh --quiet --eval 'db.adminCommand("ping").ok ? "Ready" : "Not ready"')"
echo "   Redis: $(docker exec trading-redis redis-cli ping 2>/dev/null || echo "Not available")"

echo ""
echo "🔗 Connection Information:"
echo "   PostgreSQL: localhost:5432 (user: trading_user, db: trading_results)"
echo "   MongoDB: localhost:27017 (user: admin, db: trading_configs)"
echo "   Redis: localhost:6379 (stream: trading-stats, group: trading-api-group)"
echo ""
echo "🛠️  Admin Tools (optional):"
echo "   To start admin tools: docker compose -f docker-compose.databases.yml --profile admin-tools up -d"
echo "   PgAdmin: http://localhost:5050 (admin@trading.local / admin123)"
echo "   Mongo Express: http://localhost:8081 (admin / admin123)"
echo ""
echo "🎯 Next Steps:"
echo "   1. Databases are now running persistently"
echo "   2. Start your trading services: docker compose up -d"
echo "   3. Test the API: curl http://localhost:8000/health"