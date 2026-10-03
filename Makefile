SHELL := /bin/bash
API_MANIFEST := services/api/Cargo.toml
COMPOSE := docker compose --env-file .env -f infra/dev/compose.yaml

.PHONY: dev-db dev-db-stop api api-check api-test-db api-spec api-spec-check ios-check android-check check

dev-db:
	$(COMPOSE) up -d --wait

dev-db-stop:
	$(COMPOSE) stop

api:
	set -a; source .env; set +a; cargo run --locked --manifest-path $(API_MANIFEST) --bin smallnext-api

api-check:
	cargo fmt --manifest-path $(API_MANIFEST) --all -- --check
	cargo clippy --locked --manifest-path $(API_MANIFEST) --all-targets -- -D warnings
	cargo test --locked --manifest-path $(API_MANIFEST)

api-test-db:
	set -a; source .env; set +a; TEST_DATABASE_URL="$$DATABASE_URL" cargo test --locked --manifest-path $(API_MANIFEST) --test database -- --ignored

api-spec:
	cargo run --quiet --locked --manifest-path $(API_MANIFEST) --bin export-openapi > contracts/openapi.json

api-spec-check:
	python3 scripts/check_api_spec.py

ios-check:
	if [ -n "$(IOS_SIMULATOR)" ]; then destination='platform=iOS Simulator,name=$(IOS_SIMULATOR)'; else destination="platform=iOS Simulator,id=$$(python3 scripts/ios_simulator.py)"; fi; \
	xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext -destination "$$destination" -onlyUsePackageVersionsFromResolvedFile CODE_SIGNING_ALLOWED=NO test

android-check:
	cd apps/android && ./gradlew assembleDebug lintDebug testDebugUnitTest

check:
	python3 scripts/check_repository.py
	python3 scripts/workflow_policy.py
	python3 -m unittest discover -s scripts -p 'test_*.py'
	git diff --check
	$(MAKE) api-check api-spec-check
