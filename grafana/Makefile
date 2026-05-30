# =============================================================================
# grafana/Makefile
# =============================================================================
include ../common.mk

MODULE_NAME    := grafana
VERSION        ?= 11.5.0
PORT           ?= 3000
ADMIN_PASSWORD ?= admin

.DEFAULT_GOAL := install

.PHONY: install
install: _check-root _install-package _write-config _setup-provisioning _install-service  ## 安装 Grafana
	$(call log_info,Grafana v$(VERSION) 部署完成)
	$(call log_info,访问地址: http://localhost:$(PORT))
	$(call log_info,默认账号: admin / $(ADMIN_PASSWORD))

.PHONY: _install-package
_install-package:
	@if grafana-server -v 2>&1 | grep -q "$(VERSION)"; then \
		echo -e "$(GREEN)[grafana]$(RESET) v$(VERSION) 已安装，跳过"; exit 0; \
	fi
	$(call log_info,通过 APT 安装 Grafana v$(VERSION)...)
	@$(APT) install -y apt-transport-https software-properties-common wget gnupg
	@mkdir -p /etc/apt/keyrings
	@wget -q $(if $(PROXY_HTTP),--execute=https_proxy=$(PROXY_HTTP),) \
		-O /etc/apt/keyrings/grafana.key https://apt.grafana.com/gpg.key
	@echo "deb [signed-by=/etc/apt/keyrings/grafana.key] https://apt.grafana.com stable main" \
		> /etc/apt/sources.list.d/grafana.list
	@$(APT) update -qq
	@$(APT) install -y grafana=$(VERSION)

.PHONY: _write-config
_write-config:
	@sed -i "s/^;*\s*http_port\s*=.*/http_port = $(PORT)/" /etc/grafana/grafana.ini
	@sed -i "s/^;*\s*allow_sign_up\s*=.*/allow_sign_up = false/" /etc/grafana/grafana.ini
	$(call log_info,grafana.ini 已更新（port=$(PORT)）)

.PHONY: _setup-provisioning
_setup-provisioning:
	$(call log_info,配置数据源和 Dashboard...)
	@mkdir -p /etc/grafana/provisioning/datasources
	@mkdir -p /etc/grafana/provisioning/dashboards
	@mkdir -p /var/lib/grafana/dashboards
	@bash write-provisioning.sh
	@chown -R grafana:grafana /var/lib/grafana/dashboards 2>/dev/null || true

.PHONY: _install-service
_install-service:
	$(call systemd_enable_start,grafana-server)
	$(call wait_port,$(PORT),grafana,60)
	@if [ "$(ADMIN_PASSWORD)" != "admin" ]; then \
		grafana-cli admin reset-admin-password "$(ADMIN_PASSWORD)" 2>/dev/null || true; \
	fi

# ── 运维 ──────────────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall: _check-root            ## 卸载 Grafana（保留数据库）
	$(call systemd_disable_stop,grafana-server)
	@apt-get remove -y grafana 2>/dev/null || true
	$(call log_warn,数据库 /var/lib/grafana/grafana.db 已保留)

.PHONY: status
status:                           ## 显示 Grafana 服务状态
	@systemctl status grafana-server --no-pager -l -n 5 2>/dev/null || true

.PHONY: test
test:                             ## 健康检查
	@curl -sf http://localhost:$(PORT)/api/health | grep -q '"database":"ok"' \
		|| { echo "Grafana 不健康"; exit 1; }

.PHONY: clean
clean:
	@true

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
