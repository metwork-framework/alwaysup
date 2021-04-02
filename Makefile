.PHONY: tests clean lint black coverage

lint:
	black --check alwaysup
	mypy --ignore-missing-imports alwaysup
	flake8 --max-line-length 88 --ignore=D100,D101,D102,D103,D104,D107,D106,D105,W503,E203 alwaysup
	pylint --errors-only alwaysup
	bandit -ll -r alwaysup

tests: lint
	export PYTHONPATH=".:${PYTHONPATH}"; pytest

clean:
	rm -Rf alwaysup.egg-info htmlcov
	find . -type d -name __pycache__ -exec rm -Rf {} \; >/dev/null 2>&1 || true
	find . -type d -name .mypy_cache -exec rm -Rf {} \; >/dev/null 2>&1 || true
	find . -type d -name .pytest_cache -exec rm -Rf {} \; >/dev/null 2>&1 || true

black:
	black alwaysup

coverage:
	export PYTHONPATH=".:${PYTHONPATH}"; pytest --cov=alwaysup tests/
	export PYTHONPATH=".:${PYTHONPATH}"; pytest --cov=alwaysup --cov-report=html tests/

doc:
	rm -Rf html
	pdoc3 --force --html alwaysup
