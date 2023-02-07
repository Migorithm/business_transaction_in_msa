#!/bin/bash

pipenv run alembic upgrade head
pipenv run uvicorn app.main:app --host 0.0.0.0 --port 8000
