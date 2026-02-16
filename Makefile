# SwissUnihockey Docker Management
# Convenient commands for Docker operations

.PHONY: help build up down restart logs shell preload test clean

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "SwissUnihockey Docker Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build Docker images
	@echo "Building Docker images..."
	docker-compose build

up: ## Start containers
	@echo "Starting containers..."
	docker-compose up -d

down: ## Stop containers
	@echo "Stopping containers..."
	docker-compose down

restart: down up ## Restart containers

logs: ## Show container logs
	docker-compose logs -f swissunihockey

shell: ## Open shell in container
	docker-compose exec swissunihockey /bin/bash

python: ## Open Python shell in container
	docker-compose exec swissunihockey python

preload: ## Preload cache (run once)
	@echo "Preloading cache..."
	docker-compose run --rm preload-cache

preload-auto: ## Start automatic cache refresh (hourly)
	@echo "Starting automatic cache refresher..."
	docker-compose --profile auto-refresh up -d cache-refresher

test: ## Run tests in container
	docker-compose exec swissunihockey pytest tests/

dev: ## Start development environment
	@echo "Starting development environment..."
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

dev-jupyter: ## Start with Jupyter notebook
	@echo "Starting with Jupyter Lab..."
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml --profile jupyter up -d
	@echo "Jupyter available at: http://localhost:8888"

clean: ## Clean up containers, images, and volumes
	@echo "Cleaning up..."
	docker-compose down -v
	docker system prune -f

clean-all: ## Clean everything including images
	@echo "Removing all containers, images, and volumes..."
	docker-compose down -v --rmi all
	docker system prune -af

stats: ## Show container resource usage
	docker stats swissunihockey-client

inspect: ## Inspect container
	docker-compose exec swissunihockey python -c "from api import SwissUnihockeyClient; c = SwissUnihockeyClient(); print(c.cache.get_stats())"

# Production commands
prod-build: ## Build production image
	docker build -t swissunihockey:prod .

prod-run: ## Run production container
	docker run -d --name swissunihockey-prod \
		-v $(PWD)/data/cache:/app/data/cache \
		-e SWISSUNIHOCKEY_CACHE_ENABLED=true \
		swissunihockey:prod

# Utility commands
cache-stats: ## Show cache statistics
	docker-compose exec swissunihockey python -c \
		"from api import SwissUnihockeyClient; import json; c = SwissUnihockeyClient(); print(json.dumps(c.cache.get_stats(), indent=2))"

cache-clear: ## Clear all cache
	docker-compose exec swissunihockey python -c \
		"from api import SwissUnihockeyClient; c = SwissUnihockeyClient(); c.cache.clear(); print('Cache cleared!')"

version: ## Show version info
	@echo "SwissUnihockey Docker Environment"
	@echo "Docker version:"
	@docker --version
	@echo "Docker Compose version:"
	@docker-compose --version
