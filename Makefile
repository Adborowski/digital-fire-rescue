.PHONY: setup discover fetch extract assets verify ia-backstop

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

discover:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.discover

# Full run respects robots.txt Crawl-delay: 20 by default -- at 11,431 pages
# that's ~2.6 days. Narrow with --type, or pass --delay once Tony's said ok
# to go faster. e.g. make fetch ARGS="--type recipe"
fetch:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.fetch $(ARGS)

extract:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.extract $(ARGS)

assets:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.assets $(ARGS)

verify:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.verify

ia-backstop:
	. .venv/bin/activate && PYTHONPATH=src python -m digitalfire_archive.ia_backstop $(ARGS)
