# SwissUnihockey Docker Quick Start (PowerShell)
# Run this script to set up and start the Docker environment

Write-Host "🐳 SwissUnihockey Docker Quick Start" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is installed
try {
    $dockerVersion = docker --version
    Write-Host "✅ Docker found: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker not found. Please install Docker Desktop:" -ForegroundColor Red
    Write-Host "   https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

# Check if Docker Compose is installed
try {
    $composeVersion = docker-compose --version
    Write-Host "✅ Docker Compose found: $composeVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker Compose not found. Please install Docker Compose:" -ForegroundColor Red
    Write-Host "   https://docs.docker.com/compose/install/" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Build images
Write-Host "📦 Building Docker images..." -ForegroundColor Yellow
docker-compose build

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed" -ForegroundColor Red
    exit 1
}

# Start containers
Write-Host "🚀 Starting containers..." -ForegroundColor Yellow
docker-compose up -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to start containers" -ForegroundColor Red
    exit 1
}

# Wait for container to be healthy
Write-Host "⏳ Waiting for container to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Preload cache
Write-Host "💾 Preloading cache (this may take a minute)..." -ForegroundColor Yellow
docker-compose run --rm preload-cache

Write-Host ""
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "📚 Next steps:" -ForegroundColor Cyan
Write-Host "   - View logs: docker-compose logs -f"
Write-Host "   - Python shell: docker-compose exec swissunihockey python"
Write-Host "   - Cache stats: make cache-stats"
Write-Host "   - Stop: docker-compose down"
Write-Host ""
Write-Host "📖 Full documentation: DOCKER.md" -ForegroundColor Yellow
