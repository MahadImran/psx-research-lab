.PHONY: doctor test test-collector test-all lint typecheck probe clean help

help:
	@echo "PSX Research Lab Commands:"
	@echo "  make doctor         Run environment, toolchain, and cost-guard checks"
	@echo "  make test           Run all tests (TypeScript + Python)"
	@echo "  make test-collector Run Python collector tests (pytest)"
	@echo "  make lint           Run linters across codebase"
	@echo "  make typecheck      Run TypeScript typechecker"
	@echo "  make probe          Run bounded PSX read-only probe locally"
	@echo "  make clean          Clean temporary artifacts"

doctor:
	@bash scripts/doctor.sh

test:
	@pnpm test
	@$(MAKE) test-collector

test-collector:
	@cd services/collector && python3 -m pytest -v

lint:
	@pnpm lint

typecheck:
	@pnpm typecheck

probe:
	@python3 services/collector/src/collector/probe.py --local

clean:
	@rm -rf node_modules apps/*/node_modules packages/*/node_modules
	@rm -rf services/collector/.pytest_cache services/collector/__pycache__
