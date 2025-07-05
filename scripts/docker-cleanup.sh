#!/bin/bash

# Patterns to match
PATTERNS=("market-streamer" "order-book-algo" "trade-simulator")

# Loop over patterns
for pattern in "${PATTERNS[@]}"; do
    # Find matching container IDs (running or stopped)
    CONTAINERS=$(docker ps -a --filter "name=${pattern}" --format "{{.ID}}")
    
    if [ -n "$CONTAINERS" ]; then
        echo "Stopping containers matching $pattern..."
        docker stop $CONTAINERS

        echo "Removing containers matching $pattern..."
        docker rm $CONTAINERS
    else
        echo "No containers found matching $pattern"
    fi
done


docker network prune
