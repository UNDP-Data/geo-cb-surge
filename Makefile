.PHONY: help test build down shell

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  shell            to shell in dev mode"
	@echo "  test             to execute test cases"
	@echo "  build            to build docker image"
	@echo "  down             to destroy docker containers"


shell:
	@echo
	@echo "------------------------------------------------------------------"
	@echo "Shelling in dev mode"
	@echo "------------------------------------------------------------------"
	docker compose -f docker-compose.yaml run --remove-orphans --entrypoint /bin/bash rapida


test:
	@echo
	@echo "------------------------------------------------------------------"
	@echo "Execute test cases"
	@echo "------------------------------------------------------------------"
	pipenv run python -m pytest tests

build:
	@echo
	@echo "------------------------------------------------------------------"
	@echo "Building Docker image"
	@echo "------------------------------------------------------------------"
	docker compose -f docker-compose.yaml build --build-arg PRODUCTION=$(PRODUCTION)

down:
	@echo
	@echo "------------------------------------------------------------------"
	@echo "Destroy docker containers"
	@echo "------------------------------------------------------------------"
	docker compose -f docker-compose.yaml down


