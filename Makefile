# =============================================================================
# 根 Makefile
# deploy.mode=compose → docker/compose/Makefile
# deploy.mode=k8s     → k8s/Makefile
# proxy-srv 两种模式都需要（裸机安装）
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

# ── 网络环境检测 ──────────────────────────────────────────────────────────────
ifeq ($(DEPLOY_NETWORK),auto)
  RESTRICTED_REGION := $(shell \
    curl --silent --max-time 6 --head https://www.google.com -o /dev/null 2>/dev/null \
    && echo false || echo true)
else ifeq ($(DEPLOY_NETWORK),restricted)
  RESTRICTED_REGION := true
else
  RESTRICTED_REGION := false
endif

export RESTRICTED_REGION
export PROXY_HTTP   := $(if $(filter true,$(RESTRICTED_REGION)),$(PROXY_HTTP_ADDR),)
export PROXY_SOCKS5 := $(if $(filter true,$(RESTRICTED_REGION)),$(PROXY_SOCKS5_ADDR),)

# 导出所有配置变量给子模块
export DEPLOY_MODE DEPLOY_HOST_IP DEPLOY_DOMAIN
export ETCD_VERSION ETCD_CLIENT_PORT ETCD_PEER_PORT ETCD_DATA_DIR
export ETCD_NODE_NAME ETCD_NODE_IP ETCD_NODE_COUNT ETCD_INITIAL_CLUSTER ETCD_RETENTION
export PROMETHEUS_VERSION PROMETHEUS_PORT PROMETHEUS_DATA_DIR
export PROMETHEUS_RETENTION PROMETHEUS_RET_SIZE PROMETHEUS_SCRAPE_INT
export GRAFANA_VERSION GRAFANA_PORT GRAFANA_DOMAIN GRAFANA_TLS GRAFANA_DATA_DIR
export XRAY_SOCKS_PORT XRAY_HTTP_PORT TOR_SOCKS_PORT
export CERTS_DIR CERTS_FULLCHAIN CERTS_PRIVKEY
export COMPOSE_PROJECT COMPOSE_NETWORK COMPOSE_RESTART
export K8S_NAMESPACE K8S_FLAVOR K8S_STORAGE_CLASS
export K8S_ETCD_PVC_SIZE K8S_PROM_PVC_SIZE K8S_GRAFANA_PVC_SIZE K8S_IMAGE_PULL_POLICY

# ── 颜色 ──────────────────────────────────────────────────────────────────────
BOLD  := \033[1m
CYAN  := \033[0;36m
GREEN := \033[0;32m
RED   := \033[0;31m
RESET := \033[0m

# ── 配置管理 ──────────────────────────────────────────────────────────────────

.PHONY: config-gen
config-gen:                       ## 从 config.yaml 生成 config.mk + compose/k8s 配置
	@python3 scripts/config-gen.py
	@echo -e "$(GREEN)提示: 运行 make config-show 查看当前配置$(RESET)"

.PHONY: config-check
config-check:                     ## 校验 config.yaml
	@python3 scripts/config-gen.py --check

.PHONY: config-diff
config-diff:                      ## 预览 config.yaml 变更的 diff
	@python3 scripts/config-gen.py --diff

.PHONY: config-show
config-show:                      ## 打印当前所有配置
	@echo -e "$(BOLD)部署模式  :$(RESET) $(DEPLOY_MODE)"
	@echo -e "$(BOLD)网络环境  :$(RESET) $(DEPLOY_NETWORK) → RESTRICTED_REGION=$(RESTRICTED_REGION)"
	@echo -e "$(BOLD)etcd      :$(RESET) v$(ETCD_VERSION)  :$(ETCD_CLIENT_PORT)  节点数=$(ETCD_NODE_COUNT)"
	@echo -e "$(BOLD)Prometheus:$(RESET) v$(PROMETHEUS_VERSION)  :$(PROMETHEUS_PORT)"
	@echo -e "$(BOLD)Grafana   :$(RESET) v$(GRAFANA_VERSION)  :$(GRAFANA_PORT)"
ifeq ($(DEPLOY_MODE),k8s)
	@echo -e "$(BOLD)k8s flavor:$(RESET) $(K8S_FLAVOR)  namespace=$(K8S_NAMESPACE)"
endif

# ── 部署入口（按 mode 分叉）──────────────────────────────────────────────────

.PHONY: install
install: _require-config _check-root _install-proxy   ## 部署（自动按 deploy.mode 路由）
ifeq ($(DEPLOY_MODE),compose)
	@echo -e "$(CYAN)$(BOLD)── 模式: compose ──$(RESET)"
	@$(MAKE) -C docker/compose install
else ifeq ($(DEPLOY_MODE),k8s)
	@echo -e "$(CYAN)$(BOLD)── 模式: k8s ($(K8S_FLAVOR)) ──$(RESET)"
	@$(MAKE) -C k8s install
else
	$(error 未知 DEPLOY_MODE: $(DEPLOY_MODE))
endif
	@$(MAKE) --no-print-directory _summary

# proxy-srv 两种模式都需要（裸机层）
.PHONY: _install-proxy
_install-proxy:
	@$(MAKE) -C proxy-srv install

.PHONY: uninstall
uninstall: _require-config _check-root                ## 卸载
ifeq ($(DEPLOY_MODE),compose)
	@$(MAKE) -C docker/compose uninstall
else
	@$(MAKE) -C k8s uninstall
endif

.PHONY: status
status: _require-config                               ## 查看所有服务状态
	@echo -e "$(BOLD)── proxy-srv ──$(RESET)"
	@$(MAKE) -C proxy-srv status 2>/dev/null || true
	@echo
ifeq ($(DEPLOY_MODE),compose)
	@$(MAKE) -C docker/compose status
else
	@$(MAKE) -C k8s status
endif

.PHONY: test
test: _require-config                                 ## 全量健康检查
	@echo -e "$(BOLD)健康检查 [$(DEPLOY_MODE)]$(RESET)"
	@$(MAKE) -C proxy-srv test    && echo -e "  proxy-srv   $(GREEN)PASS$(RESET)" || echo -e "  proxy-srv   $(RED)FAIL$(RESET)"
ifeq ($(DEPLOY_MODE),compose)
	@$(MAKE) -C docker/compose test
else
	@$(MAKE) -C k8s test
endif

.PHONY: logs
logs: _require-config                                 ## 查看服务日志
ifeq ($(DEPLOY_MODE),compose)
	@$(MAKE) -C docker/compose logs
else
	@$(MAKE) -C k8s logs
endif

# ── 迁移辅助 ─────────────────────────────────────────────────────────────────

.PHONY: migrate-compose-to-k8s
migrate-compose-to-k8s: _require-config               ## 辅助：compose → k8s 迁移检查
	@echo -e "$(BOLD)迁移前检查清单：$(RESET)"
	@echo "  1. 已安装 k3s/k8s？            $(shell command -v kubectl &>/dev/null && echo ✓ || echo ✗ 未安装)"
	@echo "  2. 已安装 StorageClass？        $(shell kubectl get sc 2>/dev/null | grep -c default || echo '无法检测')"
	@echo "  3. config.yaml mode=k8s？       $(shell grep 'mode:' config.yaml | grep -q k8s && echo ✓ || echo ✗ 当前是 compose)"
	@echo "  4. 数据备份完成？               请手动确认"
	@echo
	@echo "迁移步骤："
	@echo "  1. 备份数据: make backup"
	@echo "  2. 修改 config.yaml: deploy.mode: k8s"
	@echo "  3. make config-gen"
	@echo "  4. make install"

.PHONY: backup
backup:                                               ## 备份所有服务数据
	@echo -e "$(BOLD)备份数据...$(RESET)"
	@BACKUP_DIR="/tmp/infra-backup-$$(date +%Y%m%d-%H%M%S)"; \
	mkdir -p "$$BACKUP_DIR"; \
	cp -r $(ETCD_DATA_DIR) "$$BACKUP_DIR/etcd" 2>/dev/null && echo "  ✓ etcd" || echo "  - etcd (跳过)"; \
	cp -r $(PROMETHEUS_DATA_DIR) "$$BACKUP_DIR/prometheus" 2>/dev/null && echo "  ✓ prometheus" || echo "  - prometheus (跳过)"; \
	cp -r $(GRAFANA_DATA_DIR) "$$BACKUP_DIR/grafana" 2>/dev/null && echo "  ✓ grafana" || echo "  - grafana (跳过)"; \
	echo "  备份目录: $$BACKUP_DIR"

# ── 内部 ──────────────────────────────────────────────────────────────────────

.PHONY: _require-config
_require-config:
	@[ -f $(CONFIG_MK) ] || { echo -e "$(RED)请先运行 make config-gen$(RESET)"; exit 1; }

.PHONY: _check-root
_check-root:
	@[ "$$(id -u)" -eq 0 ] || { echo -e "$(RED)请以 root 运行$(RESET)"; exit 1; }

.PHONY: _summary
_summary:
	@echo
	@echo -e "$(CYAN)$(BOLD)╔═══════════════════════════════════════════════╗$(RESET)"
	@printf  "$(CYAN)$(BOLD)║$(RESET)  模式: %-38s$(CYAN)$(BOLD)║$(RESET)\n" "$(DEPLOY_MODE)"
	@printf  "$(CYAN)$(BOLD)║$(RESET)  Prometheus  http://$(DEPLOY_HOST_IP):%-16s$(CYAN)$(BOLD)║$(RESET)\n" "$(PROMETHEUS_PORT)"
	@printf  "$(CYAN)$(BOLD)║$(RESET)  Grafana     http://$(DEPLOY_HOST_IP):%-16s$(CYAN)$(BOLD)║$(RESET)\n" "$(GRAFANA_PORT)"
	@printf  "$(CYAN)$(BOLD)║$(RESET)  etcd        $(DEPLOY_HOST_IP):%-22s$(CYAN)$(BOLD)║$(RESET)\n" "$(ETCD_CLIENT_PORT)"
	@echo -e "$(CYAN)$(BOLD)╚═══════════════════════════════════════════════╝$(RESET)"

.PHONY: help
help:
	@echo -e "$(BOLD)用法: make [target]$(RESET)\n"
	@echo -e "$(BOLD)配置:$(RESET)"
	@grep -E '^config-[a-z]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*##"};{printf "  $(CYAN)%-22s$(RESET) %s\n",$$1,$$2}'
	@echo -e "\n$(BOLD)部署:$(RESET)"
	@grep -E '^(install|uninstall|status|test|logs|migrate|backup):.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*##"};{printf "  $(CYAN)%-22s$(RESET) %s\n",$$1,$$2}'
	@echo
	@echo -e "当前模式: $(BOLD)$(DEPLOY_MODE)$(RESET)"