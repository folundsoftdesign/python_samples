export PYTHON_VERSION=3.12.9
export LOCAL_REPO = dockerrepo.softdesign.dk:5000

# Install python dependencies
install:
	uv sync

# Install pre-commit hooks
pre_commit_setup:
	uv run pre-commit install

# Install python dependencies and pre-commit hooks
setup: install pre_commit_setup

# Run pre-commit
pre_commit:
	uv run pre-commit run -a

# Update dependencies
update:
	uv lock --upgrade

# Run pytest
test:
	uv run pytest

# Run formatter
format: 
	uv run ruff check --select I --fix
	uv run ruff format

# Run linter
lint:
	uv run ruff check
	uv run mypy .

run-sample:
	cd apps/sample && uv run fastapi dev sample/server.py

run-worker:
	uv run --directory=apps/playground fastapi dev playground/worker_sqlite.py

# MONGO
# Connection string inside dev container: mongodb://root:secret@172.17.0.1:30001/?ssl=false&readPreference=primary
mongo-clean:
	-@docker stop local-mongo
	-@docker rm local-mongo
	-@docker run -e MONGO_INITDB_ROOT_USERNAME=root -e MONGO_INITDB_ROOT_PASSWORD=secret -d --name local-mongo -p 30001:27017 mongo
	-@docker start local-mongo

mongo:
	-@docker stop local-mongo
	-@docker start local-mongo	


# JENKINS BUILD, TEST AND DEPLOY - DO NOT TOUCH
# ----------------------------------------------
jenkins-build: 
	@./devops/docker_scripts.sh build ${APPLICATION}

jenkins-test: 
	@./devops/docker_scripts.sh test ${APPLICATION}

jenkins-build-prod: 
	@./devops/docker_scripts.sh build-prod ${APPLICATION}

jenkins-repo-push:
	@./devops/docker_scripts.sh repo-push ${APPLICATION}

jenkins-run:
	@./devops/docker_scripts.sh run ${APPLICATION}
# --