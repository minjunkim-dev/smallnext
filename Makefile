SHELL := /bin/bash
API_MANIFEST := services/api/Cargo.toml
COMPOSE := docker compose --env-file .env -f infra/dev/compose.yaml

.PHONY: dev-db dev-db-stop api api-check api-test-db api-spec api-spec-check ios-check android-check android-device-check android-sdk api-setup repository-check api-image-build api-image-check check

api-setup:
	python3 scripts/environment.py rust-install

android-sdk:
	python3 scripts/environment.py android-install

dev-db:
	$(COMPOSE) up -d --wait

dev-db-stop:
	$(COMPOSE) stop

api:
	set -a; source .env; set +a; cargo run --locked --manifest-path $(API_MANIFEST) --bin smallnext-api

api-check:
	python3 scripts/environment.py rust
	cargo fmt --manifest-path $(API_MANIFEST) --all -- --check
	cargo clippy --locked --manifest-path $(API_MANIFEST) --all-targets -- -D warnings
	cargo test --locked --manifest-path $(API_MANIFEST)

api-test-db:
	set -eu; if [ -z "$${TEST_DATABASE_URL:-}" ]; then set -a; source .env; set +a; export TEST_DATABASE_URL="$$DATABASE_URL"; fi; \
	cargo test --locked --manifest-path $(API_MANIFEST) --test database -- --ignored

api-spec:
	cargo run --quiet --locked --manifest-path $(API_MANIFEST) --bin export-openapi > contracts/openapi.json

api-spec-check:
	python3 scripts/check_api_spec.py

ios-check:
	bash scripts/check_ios.sh

android-check:
	python3 scripts/environment.py android
	cd apps/android && ./gradlew --no-daemon --parallel --build-cache assembleDebug assembleDebugAndroidTest lintDebug testDebugUnitTest

android-device-check:
	python3 scripts/environment.py android
	cd apps/android && ./gradlew --no-daemon --parallel --build-cache connectedDebugAndroidTest

api-image-build:
	docker buildx build --load --progress plain --file services/api/Dockerfile --tag smallnext-api:ci $(IMAGE_BUILD_ARGS) .

api-image-check:
	test "$$(docker run --rm --entrypoint id smallnext-api:ci -u)" = 10001
	docker compose --env-file .env.example -f infra/dev/compose.yaml config --quiet
	API_DOMAIN=api.example.invalid DATABASE_URL=postgres://example:example@database.invalid/smallnext docker compose -f infra/production/compose.yaml config --quiet

repository-check:
	python3 scripts/check_repository.py
	python3 scripts/workflow_policy.py
	python3 -m unittest discover -s scripts -p 'test_*.py'
	git diff --check

check: repository-check api-check api-spec-check
