# =============================================================================
# etcd/Makefile
# =============================================================================
include ../common.mk

MODULE_NAME   := etcd
VERSION       ?= 3.6.0
DATA_DIR      := /var/lib/etcd
CONF_DIR      := /etc/etcd
BIN_DIR       := /usr/local/bin
ETCD_USER     := etcd

NODE_NAME     ?= etcd-node-1
NODE_IP       ?= 127.0.0.1
INITIAL_CLUSTER ?= $(NODE_NAME)=http://$(NODE_IP):2380

TARBALL       := etcd-v$(VERSION)-linux-$(ARCH).tar.gz
DOWNLOAD_URL  := https://github.com/etcd-io/etcd/releases/download/v$(VERSION)/$(TARBALL)
TMP_DIR       := /tmp/etcd-install

.DEFAULT_GOAL := install

.PHONY: install
install: _check-root _download _setup-system _write-config _install-service  ## 安装 etcd
	$(call log_info,etcd v$(VERSION) 部署完成)
	$(call log_info,客户端端口: 2379  集群端口: 2380)

.PHONY: _download
_download:
	@if etcd --version 2>&1 | grep -q "$(VERSION)"; then \
		echo -e "$(GREEN)[etcd]$(RESET) v$(VERSION) 已安装，跳过下载"; exit 0; \
	fi
	$(call log_info,下载 etcd v$(VERSION) $(ARCH)...)
	@mkdir -p $(TMP_DIR)
	@$(CURL) $(DOWNLOAD_URL) -o $(TMP_DIR)/$(TARBALL)
	@tar -xzf $(TMP_DIR)/$(TARBALL) -C $(TMP_DIR)
	@install -m 755 $(TMP_DIR)/etcd-v$(VERSION)-linux-$(ARCH)/etcd    $(BIN_DIR)/etcd
	@install -m 755 $(TMP_DIR)/etcd-v$(VERSION)-linux-$(ARCH)/etcdctl $(BIN_DIR)/etcdctl
	@install -m 755 $(TMP_DIR)/etcd-v$(VERSION)-linux-$(ARCH)/etcdutl $(BIN_DIR)/etcdutl
	@rm -rf $(TMP_DIR)
	$(call log_info,etcd $$(etcd --version | head -1))

.PHONY: _setup-system
_setup-system:
	@id $(ETCD_USER) &>/dev/null || useradd --system --no-create-home --shell /bin/false $(ETCD_USER)
	@mkdir -p $(DATA_DIR) $(CONF_DIR)
	@chown $(ETCD_USER):$(ETCD_USER) $(DATA_DIR)

.PHONY: _write-config
_write-config:
	$(call log_info,写入配置: $(CONF_DIR)/etcd.conf.yml)
	@cat > $(CONF_DIR)/etcd.conf.yml <<-'EOF'
	name: '$(NODE_NAME)'
	data-dir: '$(DATA_DIR)'
	listen-client-urls: 'http://0.0.0.0:2379'
	advertise-client-urls: 'http://$(NODE_IP):2379'
	listen-peer-urls: 'http://0.0.0.0:2380'
	initial-advertise-peer-urls: 'http://$(NODE_IP):2380'
	initial-cluster: '$(INITIAL_CLUSTER)'
	initial-cluster-token: 'infra-etcd-cluster'
	initial-cluster-state: 'new'
	log-level: 'info'
	log-outputs: ['systemd/journal']
	auto-compaction-mode: 'periodic'
	auto-compaction-retention: '1h'
	heartbeat-interval: 100
	election-timeout: 1000
	snapshot-count: 10000
	EOF
	@chmod 640 $(CONF_DIR)/etcd.conf.yml
	@chown root:$(ETCD_USER) $(CONF_DIR)/etcd.conf.yml

.PHONY: _install-service
_install-service:
	@cat > /etc/systemd/system/etcd.service <<-EOF
	[Unit]
	Description=etcd key-value store
	Documentation=https://etcd.io/docs/
	After=network.target

	[Service]
	User=$(ETCD_USER)
	Type=notify
	ExecStart=$(BIN_DIR)/etcd --config-file $(CONF_DIR)/etcd.conf.yml
	Restart=on-failure
	RestartSec=5s
	LimitNOFILE=65536

	[Install]
	WantedBy=multi-user.target
	EOF
	$(call systemd_enable_start,etcd)
	$(call wait_port,2379,etcd,30)

# ── 运维 ──────────────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall: _check-root            ## 卸载 etcd（保留数据目录）
	$(call systemd_disable_stop,etcd)
	@rm -f $(BIN_DIR)/etcd $(BIN_DIR)/etcdctl $(BIN_DIR)/etcdutl
	@rm -f /etc/systemd/system/etcd.service
	$(call log_warn,数据目录 $(DATA_DIR) 已保留，手动删除: rm -rf $(DATA_DIR))

.PHONY: status
status:                           ## 显示 etcd 状态和集群成员
	@systemctl status etcd --no-pager -l -n 5 2>/dev/null || true
	@echo
	@etcdctl endpoint status --endpoints=http://127.0.0.1:2379 \
		--write-out=table 2>/dev/null || true

.PHONY: test
test:                             ## 健康检查
	@etcdctl endpoint health --endpoints=http://127.0.0.1:2379 2>/dev/null \
		|| { echo "etcd 不健康"; exit 1; }

.PHONY: clean
clean:                            ## 清理下载缓存
	@rm -rf $(TMP_DIR)

# ── 分布式扩展帮助 ─────────────────────────────────────────────────────────────
.PHONY: cluster-hint
cluster-hint:                     ## 显示 3 节点集群部署示例
	@echo "3 节点集群部署示例（每台机器分别执行）:"
	@echo
	@echo "  # 节点 1（10.0.0.1）"
	@echo "  make -C etcd install \\"
	@echo "    NODE_NAME=etcd-1 NODE_IP=10.0.0.1 \\"
	@echo "    INITIAL_CLUSTER='etcd-1=http://10.0.0.1:2380,etcd-2=http://10.0.0.2:2380,etcd-3=http://10.0.0.3:2380'"
	@echo
	@echo "  # 节点 2/3 类似，修改 NODE_NAME 和 NODE_IP"

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
