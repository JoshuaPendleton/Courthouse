.PHONY: setup run test status
setup:
	sh ./install_dependencies.sh
run:
	sh ./run.sh
test:
	python3 -m unittest discover -s tests -v
status:
	python3 scripts/check_agents.py
