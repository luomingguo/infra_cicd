# =============================================================================
# 根 Makefile — 纯编排层
#
# 不知道有哪些模块，不知道模块内部有哪些变量。
# 模块列表、顺序、mode 过滤全部来自 config.mk（由 config.yaml 生成）。
# =============================================================================

SHELL         := /bin/bash
.DEFAULT_GOAL := help

CONFIG_MK := config.mk

ifeq ($(wildcard $(CONFIG_MK)),)
  $(info  首次使用请运行: make config-gen)
  TARGETS_NO_CONFIG := config-gen config-check config-diff help
  ifeq ($(filter $(TARGETS_NO_CONFIG), $(MAKECMDGOALS)),)
    $(error 请先运行 make config-gen)
  endif
else
  include $(CONFIG_MK)
endif

# ── 网络环境检测（写入 runtime.mk，子模块 include 获取）──────────────────────
ifeq ($(DEPLOY_NETWORK),auto)
  RESTRICTED_REGION := $(shell \
    curl --silent --max-time 6 --head https://www.google.com -o /dev/null 2>/dev/null \
    && echo false || echo true)
else ifeq ($(DEPLOY_NETWORK),restricted)
  RESTRICTED_REGION := true
else
  RESTRICTED_REGION := false
endif

export INFRA_CONFIG_MK  := $(CURDIR)/config.mk
export INFRA_RUNTIME_MK := $(CURDIR)/runtime.mk
export INFRA_COMMON_MK  := $(CURDIR)/common.mk

$(shell python3 -c "r='$(RESTRICTED_REGION)';h='$(if $(filter true,$(RESTRICTED_REGION)),$(PROXY_HTTP_ADDR),)';s='$(if $(filter true,$(RESTRICTED_REGION)),$(PROXY_SOCKS5_ADDR),)';open('runtime.mk','w').write('# 自动生成，勿手动编辑\nRESTRICTED_REGION := '+r+'\nPROXY_HTTP        := '+h+'\nPROXY_SOCKS5      := '+s+'\n')")

# 颜色 / 工具函数来自 common.mk（颜色只在这里定义一次）
include common.mk

# ── 配置管理 ──────────────────────────────────────────────────────────────────

.PHONY: config-gen
config-gen:                       ## 从 config.yaml 生成 config.mk + compose/k8s 配置
	@python3 scripts/config-gen.py
	@echo -e "$(GREEN)提示: 运行 make config-show 查看当前配置$(RESET)"

.PHONY: config-check
config-check:                     ## 校验 config.yaml（端口冲突、必填项、模块格式）
	@python3 scripts/config-gen.py --check

.PHONY: config-diff
config-diff:                      ## 预览 config.yaml 变更会产生哪些 config.mk 差异
	@python3 scripts/config-gen.py --diff

.PHONY: config-show
config-show:                      ## 打印当前生效的模块列表和关键配置
	@echo -e "$(BOLD)部署模式  :$(RESET) $(DEPLOY_MODE)"
	@echo -e "$(BOLD)网络环境  :$(RESET) $(DEPLOY_NETWORK) → RESTRICTED_REGION=$(RESTRICTED_REGION)"
	@echo -e "$(BOLD)模块列表  :$(RESET)"
	@for mod in $(DEPLOY_MODULES); do echo "  $$mod"; done

# ── 部署（纯循环，不感知任何具体模块）───────────────────────────────────────

.PHONY: install
install: _require-config          ## 按 config.yaml 顺序部署所有模块
	@echo -e "$(CYAN)$(BOLD)infra_cicd deploy [mode=$(DEPLOY_MODE)]$(RESET)"
	@for mod in $(DEPLOY_MODULES); do \
		echo -e "\n$(CYAN)$(BOLD)── $$mod ──$(RESET)"; \
		$(MAKE) -C $$mod install \
			|| { echo -e "$(RED)[FAIL] $$mod$(RESET)"; exit 1; }; \
		echo -e "$(GREEN)[DONE] $$mod$(RESET)"; \
	done
	@$(MAKE) --no-print-directory _summary

.PHONY: uninstall
uninstall: _require-config        ## 按逆序卸载所有模块
	@for mod in $$(echo $(DEPLOY_MODULES) | tr ' ' '\n' | tac); do \
		$(MAKE) -C $$mod uninstall 2>/dev/null || true; \
	done

.PHONY: status
status: _require-config           ## 查看所有模块运行状态
	@for mod in $(DEPLOY_MODULES); do \
		echo -e "$(BOLD)── $$mod ──$(RESET)"; \
		$(MAKE) -C $$mod status 2>/dev/null || echo "  (无 status target)"; \
		echo; \
	done

.PHONY: test
test: _require-config             ## 全量健康检查
	@echo -e "$(BOLD)健康检查$(RESET)"
	@failed=""; \
	for mod in $(DEPLOY_MODULES); do \
		printf "  %-24s" "$$mod"; \
		if $(MAKE) -C $$mod test -s 2>/dev/null; then \
			echo -e "$(GREEN)PASS$(RESET)"; \
		else \
			echo -e "$(RED)FAIL$(RESET)"; \
			failed="$$failed $$mod"; \
		fi; \
	done; \
	[ -z "$$failed" ] \
		&& echo -e "\n$(GREEN)$(BOLD)全部通过$(RESET)" \
		|| { echo -e "\n$(RED)失败: $$failed$(RESET)"; exit 1; }

.PHONY: logs
logs: _require-config             ## 查看所有模块日志（支持 logs 的模块）
	@for mod in $(DEPLOY_MODULES); do \
		$(MAKE) -C $$mod logs 2>/dev/null || true; \
	done

# ── 迁移 / 备份 ───────────────────────────────────────────────────────────────

.PHONY: migrate-compose-to-k8s
migrate-compose-to-k8s:           ## compose → k8s 迁移检查清单
	@echo -e "$(BOLD)迁移前检查清单：$(RESET)"
	@echo "  kubectl 可用？  $(shell command -v kubectl &>/dev/null && echo ✓ || echo ✗)"
	@echo "  当前 mode？     $(DEPLOY_MODE)"
	@echo
	@echo "迁移步骤："
	@echo "  1. make backup"
	@echo "  2. 修改 config.yaml: deploy.mode: k8s"
	@echo "  3. make config-gen && make install"

.PHONY: backup
backup:                           ## 调用每个模块的 backup target（有则执行）
	@BACKUP_DIR="/tmp/infra-backup-$$(date +%Y%m%d-%H%M%S)"; \
	mkdir -p "$$BACKUP_DIR"; \
	echo -e "$(BOLD)备份目录: $$BACKUP_DIR$(RESET)"; \
	for mod in $(DEPLOY_MODULES); do \
		$(MAKE) -C $$mod backup BACKUP_DIR="$$BACKUP_DIR" 2>/dev/null \
			&& echo "  ✓ $$mod" || true; \
	done

# ── 内部 ──────────────────────────────────────────────────────────────────────

.PHONY: _require-config
_require-config:
	@[ -f $(CONFIG_MK) ] || { echo -e "$(RED)请先运行 make config-gen$(RESET)"; exit 1; }

.PHONY: _summary
_summary:
	@echo
	@echo -e "$(CYAN)$(BOLD)╔══════════════════════════════════════╗$(RESET)"
	@printf  "$(CYAN)$(BOLD)║$(RESET)  mode=%-32s$(CYAN)$(BOLD)║$(RESET)\n" "$(DEPLOY_MODE)"
	@echo -e "$(CYAN)$(BOLD)╠══════════════════════════════════════╣$(RESET)"
	@for entry in $(DEPLOY_SUMMARIES); do \
		mod=$$(echo $$entry | cut -d'|' -f1); \
		url=$$(echo $$entry | cut -d'|' -f2); \
		printf "$(CYAN)$(BOLD)║$(RESET)  %-14s %-22s$(CYAN)$(BOLD)║$(RESET)\n" "$$mod" "$$url"; \
	done
	@echo -e "$(CYAN)$(BOLD)╚══════════════════════════════════════╝$(RESET)"

.PHONY: clean
clean:                            ## 删除所有生成文件（config.mk / runtime.mk / compose / k8s manifests）
	@for mod in $(DEPLOY_MODULES); do \
		$(MAKE) -C $$mod clean 2>/dev/null || true; \
	done
	@rm -f config.mk runtime.mk
	@rm -f docker/compose/docker-compose.yml
	@rm -rf k8s/manifests/
	@echo -e "$(GREEN)已清理所有生成文件$(RESET)"

.PHONY: help
help:
	@echo -e "$(BOLD)用法: make [target]$(RESET)\n"
	@echo -e "$(BOLD)配置:$(RESET)"
	@grep -E '^config-[a-z]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*##"};{printf "  $(CYAN)%-22s$(RESET) %s\n",$$1,$$2}'
	@echo -e "\n$(BOLD)部署:$(RESET)"
	@grep -E '^(install|uninstall|status|test|logs|migrate|backup|clean):.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*##"};{printf "  $(CYAN)%-22s$(RESET) %s\n",$$1,$$2}'
	@echo
	@echo -e "当前模块: $(BOLD)$(DEPLOY_MODULES)$(RESET)"
