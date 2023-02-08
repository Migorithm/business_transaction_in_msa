include .env
EXPORT = export PYTHONPATH=$(PWD)

migration:
	$(EXPORT) && pipenv run alembic revision --autogenerate -m "initial tables"

upgrade:
	$(EXPORT) && pipenv run alembic upgrade head

downgrade:
	$(EXPORT) && pipenv run alembic downgrade -1


checks:
	$(EXPORT) && pipenv run sh scripts/checks.sh

docker-init:
	$(EXPORT) && pipenv run sh scripts/docker-init.sh