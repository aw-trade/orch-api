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

echo "✅ Databases are ready!"

# Show database status
echo "📊 Database Status:"
echo "   PostgreSQL: $(docker exec trading-postgres pg_isready -U trading_user -d trading_results)"
echo "   MongoDB: $(docker exec trading-mongodb mongosh --quiet --eval 'db.adminCommand("ping").ok ? "Ready" : "Not ready"')"

echo ""
echo "🔗 Connection Information:"
echo "   PostgreSQL: localhost:5432 (user: trading_user, db: trading_results)"
echo "   MongoDB: localhost:27017 (user: admin, db: trading_configs)"
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