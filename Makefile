.PHONY: build init-db preflight mapper daily email logs tracker backtest validate test-all branch-check sync-dev release-main

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

tracker:
	docker compose run --rm --entrypoint "" stock-report python -m analysis.signal_tracker

backtest:
	docker compose run --rm --entrypoint "" stock-report python -m analysis.backtest_report

logs:
	docker compose logs -f

validate:
	python -m analysis.validate_pipeline

test-all:
	python -m analysis.daily_report --mode both --force
	python -m analysis.signal_tracker
	python -m analysis.backtest_report
	python -m analysis.validate_pipeline

branch-check:
	git branch
	git status

sync-dev:
	git checkout dev
	git pull origin dev
	git merge origin/main
	git push origin dev

release-main:
	git checkout main
	git pull origin main
	git merge dev
	git push origin main
