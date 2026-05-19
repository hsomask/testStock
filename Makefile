.PHONY: build init-db preflight mapper daily email logs

build:
	docker compose build

init-db:
	docker compose run --rm --entrypoint "" stock-report python -m analysis.init_db

preflight:
	docker compose run --rm --entrypoint "" stock-report python -m analysis.preflight_check

mapper:
	docker compose run --rm stock-mapper

daily:
	docker compose run --rm stock-report

email:
	docker compose run --rm --entrypoint "" stock-report python -m analysis.email_sender

logs:
	docker compose logs -f
