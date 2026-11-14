.PHONY: setup run test status agents
agents:
	python3 scripts/download_agents.py
setup:
	sh ./install_dependencies.sh
run:
	sh ./run.sh
test:
	python3 -m unittest discover -s tests -v
status:
	python3 scripts/check_agents.py
