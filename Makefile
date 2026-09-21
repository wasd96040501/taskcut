# taskcut -- see README.md. Every target is a thin wrapper: the work lives in
# scripts/ and eval/, so nothing here is the only way to do anything.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON  ?= python3
WORKLOAD ?= synthetic
ARM      ?= off
MODEL    ?= sonnet
RESULTS  ?= eval/results

export PYTHONPATH := eval

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Benchmark variables: WORKLOAD=$(WORKLOAD) ARM=$(ARM) MODEL=$(MODEL)"

.PHONY: test
test: ## Run the plugin's unit tests
	@./scripts/test.sh

.PHONY: validate
validate: ## Everything CI runs: manifests, plugin validate, tests, types
	@./scripts/validate.sh

.PHONY: eval-test
eval-test: ## Run the benchmark harness's own tests
	@$(PYTHON) -m unittest discover -s eval/tests -t eval -v

.PHONY: eval-list
eval-list: ## Show the available workloads and arms
	@$(PYTHON) -m taskcut_eval.cli list

.PHONY: eval-verify
eval-verify: ## Check every probe is answerable from the material it ships with
	@$(PYTHON) -m taskcut_eval.cli verify

.PHONY: eval-run
eval-run: ## Run one workload under one arm (WORKLOAD=, ARM=, MODEL=)
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) run --workload $(WORKLOAD) --arm $(ARM) --model $(MODEL)

.PHONY: eval-ab
eval-ab: ## Run both arms of one workload and print the comparison (WORKLOAD=, MODEL=)
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) run --workload $(WORKLOAD) --arm off --model $(MODEL)
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) run --workload $(WORKLOAD) --arm on --model $(MODEL)
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) report

.PHONY: eval-mechanism
eval-mechanism: ## Check the mechanism end to end in one short real session (MODEL=)
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) mechanism --model $(MODEL)

.PHONY: eval-report
eval-report: ## Render the collected transcripts
	@$(PYTHON) -m taskcut_eval.cli --results $(RESULTS) report

.PHONY: check
check: validate eval-test ## validate + the harness tests

.PHONY: clean
clean: ## Remove generated types, results and benchmark scratch
	@rm -rf .claude/types $(RESULTS)/*.jsonl "$$HOME/.cache/taskcut-eval"
	@echo "cleaned"
