PYTHON ?= .venv/bin/python
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: run predict evaluate test
run:
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

predict:
	@test -n "$(IN)" || (echo 'Укажите IN=tickets.jsonl' >&2; exit 2)
	@test -n "$(OUT)" || (echo 'Укажите OUT=pred.jsonl' >&2; exit 2)
	$(PYTHON) -m scripts.predict --input "$(IN)" --output "$(OUT)"

evaluate:
	$(PYTHON) -m scripts.evaluate

test:
	SUPPORT_AI=off $(PYTHON) -m pytest -q

.PHONY: ai-serve ai-pull evaluate-ai
ai-serve:
	OLLAMA_MODELS="$(CURDIR)/work/models" OLLAMA_NO_CLOUD=1 work/ollama/ollama serve

ai-pull:
	work/ollama/ollama pull qwen3:1.7b

evaluate-ai:
	SUPPORT_AI=auto $(PYTHON) -m scripts.evaluate_ai

.PHONY: dev
dev:
	$(PYTHON) -m scripts.dev
