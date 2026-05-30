# =============================================================================
# prometheus/Makefile
# =============================================================================
include ../common.mk

MODULE_NAME    := prometheus
VERSION        ?= 3.8.0
NE_VERSION     ?= 1.8.2    # node_exporter version

DATA_DIR       := /var/lib/prometheus
CONF_DIR       := /etc/prometheus
BIN_DIR        := /usr/local/bin
PROM_USER      := prometheus

TARBALL        := prometheus-$(VERSION).linux-$(ARCH).tar.gz
DOWNLOAD_URL   := https://github.com/prometheus/prometheus/releases/download/v$(VERSION)/$(TARBALL)
NE_TARBALL     := node_exporter-$(NE_VERSION).linux-$(ARCH).tar.gz
NE_URL         := https://github.com/prometheus/node_exporter/releases/download/v$(NE_VERSION)/$(NE_TARBALL)
TMP_DIR        := /tmp/prometheus-install

.DEFAULT_GOAL := install

.PHONY: install
install: _check-root _download _setup-system _write-config _install-node-exporter _install-service  ## 安装 Prometheus + node_exporter
	$(call log_info,Prometheus v$(VERSION) 部署完成)
	$(call log_info,Web UI: http://localhost:9090)

.PHONY: _download
_download:
	@if prometheus --version 2>&1 | grep -q "$(VERSION)"; then \
		echo -e "$(GREEN)[prometheus]$(RESET) v$(VERSION) 已安装，跳过下载"; exit 0; \
	fi
	$(call log_info,下载 Prometheus v$(VERSION)...)
	@mkdir -p $(TMP_DIR)
	@$(CURL) $(DOWNLOAD_URL) -o $(TMP_DIR)/$(TARBALL)
	@tar -xzf $(TMP_DIR)/$(TARBALL) -C $(TMP_DIR)
	@install -m 755 $(TMP_DIR)/prometheus-$(VERSION).linux-$(ARCH)/prometheus $(BIN_DIR)/prometheus
	@install -m 755 $(TMP_DIR)/prometheus-$(VERSION).linux-$(ARCH)/promtool   $(BIN_DIR)/promtool
	@mkdir -p $(CONF_DIR)/consoles $(CONF_DIR)/console_libraries
	@cp -r $(TMP_DIR)/prometheus-$(VERSION).linux-$(ARCH)/consoles/*          $(CONF_DIR)/consoles/
	@cp -r $(TMP_DIR)/prometheus-$(VERSION).linux-$(ARCH)/console_libraries/* $(CONF_DIR)/console_libraries/
	@rm -rf $(TMP_DIR)

.PHONY: _setup-system
_setup-system:
	@id $(PROM_USER) &>/dev/null || useradd --system --no-create-home --shell /bin/false $(PROM_USER)
	@mkdir -p $(DATA_DIR) $(CONF_DIR)/rules
	@chown $(PROM_USER):$(PROM_USER) $(DATA_DIR) $(CONF_DIR)

.PHONY: _write-config
_write-config:
	@if [ -f $(CONF_DIR)/prometheus.yml ]; then \
		echo -e "$(YELLOW)[prometheus]$(RESET) 配置文件已存在，跳过覆盖"; exit 0; \
	fi
	$(call log_info,写入默认配置...)
	@bash write-config.sh $(CONF_DIR)
	@chown -R $(PROM_USER):$(PROM_USER) $(CONF_DIR)
	@promtool check config $(CONF_DIR)/prometheus.yml
	$(call log_info,配置校验通过 ✓)

.PHONY: _install-node-exporter
_install-node-exporter:
	@if command -v node_exporter &>/dev/null; then \
		echo -e "$(GREEN)[prometheus]$(RESET) node_exporter 已安装，跳过"; exit 0; \
	fi
	$(call log_info,安装 node_exporter v$(NE_VERSION)...)
	@mkdir -p $(TMP_DIR)
	@$(CURL) $(NE_URL) -o $(TMP_DIR)/$(NE_TARBALL)
	@tar -xzf $(TMP_DIR)/$(NE_TARBALL) -C $(TMP_DIR)
	@install -m 755 $(TMP_DIR)/node_exporter-$(NE_VERSION).linux-$(ARCH)/node_exporter $(BIN_DIR)/node_exporter
	@rm -rf $(TMP_DIR)
	@cat > /etc/systemd/system/node_exporter.service <<-EOF
	[Unit]
	Description=Prometheus Node Exporter
	After=network.target
	[Service]
	User=nobody
	ExecStart=$(BIN_DIR)/node_exporter --collector.systemd --collector.processes
	Restart=on-failure
	[Install]
	WantedBy=multi-user.target
	EOF
	$(call systemd_enable_start,node_exporter)

.PHONY: _install-service
_install-service:
	@cat > /etc/systemd/system/prometheus.service <<-EOF
	[Unit]
	Description=Prometheus Monitoring System
	After=network.target
	[Service]
	User=$(PROM_USER)
	ExecStart=$(BIN_DIR)/prometheus \
	  --config.file=$(CONF_DIR)/prometheus.yml \
	  --storage.tsdb.path=$(DATA_DIR) \
	  --storage.tsdb.retention.time=30d \
	  --storage.tsdb.retention.size=10GB \
	  --web.listen-address=0.0.0.0:9090 \
	  --web.enable-lifecycle \
	  --web.enable-admin-api
	Restart=on-failure
	RestartSec=5s
	LimitNOFILE=65536
	[Install]
	WantedBy=multi-user.target
	EOF
	$(call systemd_enable_start,prometheus)
	$(call wait_port,9090,prometheus,30)

# ── 运维 ──────────────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall: _check-root            ## 卸载 Prometheus（保留数据）
	$(call systemd_disable_stop,prometheus)
	$(call systemd_disable_stop,node_exporter)
	@rm -f $(BIN_DIR)/prometheus $(BIN_DIR)/promtool $(BIN_DIR)/node_exporter
	@rm -f /etc/systemd/system/prometheus.service /etc/systemd/system/node_exporter.service
	$(call log_warn,数据目录 $(DATA_DIR) 已保留)

.PHONY: status
status:                           ## 显示 Prometheus 状态
	@systemctl status prometheus --no-pager -l -n 5 2>/dev/null || true

.PHONY: test
test:                             ## 健康检查
	@curl -sf http://localhost:9090/-/ready || { echo "Prometheus 不可达"; exit 1; }
	@curl -sf http://localhost:9100/metrics > /dev/null || { echo "node_exporter 不可达"; exit 1; }

.PHONY: reload
reload:                           ## 热重载配置（无需重启）
	@promtool check config $(CONF_DIR)/prometheus.yml
	@curl -sf -X POST http://localhost:9090/-/reload
	$(call log_info,配置已热重载)

.PHONY: clean
clean:
	@rm -rf $(TMP_DIR)

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
