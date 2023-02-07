#!/bin/sh -e
set -x

bandit -r . -s B101,B105,B107 -x ./app/tests -lll
flake8 .
isort .
black .
mypy -p app --check-untyped-defs