#!/bin/bash
# Quick start script for SwissUnihockey Docker environment

set -e

echo "🐳 SwissUnihockey Docker Quick Start"
echo "===================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first:"
    echo "   https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker found: $(docker --version)"
echo "✅ Docker Compose found: $(docker-compose --version)"
echo ""

# Build images
echo "📦 Building Docker images..."
docker-compose build

# Start containers
echo "🚀 Starting containers..."
docker-compose up -d

# Wait for container to be healthy
echo "⏳ Waiting for container to be ready..."
sleep 5

# Preload cache
echo "💾 Preloading cache (this may take a minute)..."
docker-compose run --rm preload-cache

echo ""
echo "✅ Setup complete!"
echo ""
echo "📚 Next steps:"
echo "   - View logs: docker-compose logs -f"
echo "   - Python shell: docker-compose exec swissunihockey python"
echo "   - Cache stats: docker-compose exec swissunihockey python -c 'from api import SwissUnihockeyClient; print(SwissUnihockeyClient().cache.get_stats())'"
echo "   - Stop: docker-compose down"
echo ""
echo "📖 Full documentation: DOCKER.md"
