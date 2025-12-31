# Makefile for Green-But-Dead Detector

.PHONY: help install test lint clean run docker k8s

help:  ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install dependencies
	pip install -r requirements.txt

install-dev:  ## Install dev dependencies
	pip install -r requirements-dev.txt

test:  ## Run tests
	pytest tests/ -v

lint:  ## Run linters
	flake8 src/ tests/
	mypy src/

clean:  ## Clean generated files
	rm -rf __pycache__/ **/__pycache__/ .pytest_cache/ htmlcov/ .coverage

run:  ## Run detector
	python src/main.py --config config/detector-policy.yaml

docker:  ## Build and run Docker
	docker build -t detector .
	docker run --rm -v $(PWD)/config:/app/config detector

k8s:  ## Deploy to Kubernetes
	kubectl apply -f k8s/
