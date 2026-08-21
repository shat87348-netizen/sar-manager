.PHONY: test config build up down scan logs offline-bundle

test:
	python3 -m unittest discover -s tests -v

config:
	docker compose config >/dev/null

build:
	docker compose build api

up:
	docker compose up -d

down:
	docker compose down

scan:
	docker compose run --rm scanner

logs:
	docker compose logs -f api

offline-bundle:
	./scripts/build-offline-bundle.sh
