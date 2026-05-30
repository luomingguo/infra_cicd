# =============================================================================
# proxy-srv/Makefile
# 受限区域：xray-core + tor + lyrebird
# 非受限区域：仅 tor + lyrebird
#
# 幂等性：xray / tor 已运行时直接跳过，不重复安装
# =============================================================================

include $(or $(INFRA_COMMON_MK), ../common.mk)

MODULE_NAME  := proxy-srv
XRAY_SUB_URL ?=

# ── 状态检测（make 解析阶段）─────────────────────────────────────────────────
XRAY_READY := $(shell \
  command -v xray &>/dev/null \
  && systemctl is-active --quiet xray 2>/dev/null \
  && echo true || echo false)

TOR_READY := $(shell \
  systemctl is-active --quiet tor@default 2>/dev/null \
  && nc -z 127.0.0.1 $(TOR_SOCKS_PORT) 2>/dev/null \
  && echo true || echo false)

.DEFAULT_GOAL := install

# ── install ───────────────────────────────────────────────────────────────────
.PHONY: install
install:                          ## 安装代理层（已运行的组件自动跳过）
	$(call require_root)
	@echo -e "$(CYAN)[proxy-srv]$(RESET) RESTRICTED_REGION=$(RESTRICTED_REGION)"
	@echo -e "$(CYAN)[proxy-srv]$(RESET) xray=$(XRAY_READY)  tor=$(TOR_READY)"
ifeq ($(RESTRICTED_REGION),true)
	@$(MAKE) --no-print-directory _ensure-xray
	@$(MAKE) --no-print-directory _ensure-tor
	@$(MAKE) --no-print-directory _apply-torrc
else
	@$(MAKE) --no-print-directory _ensure-tor
endif

# ── xray ──────────────────────────────────────────────────────────────────────
.PHONY: _ensure-xray
_ensure-xray:
ifeq ($(XRAY_READY),true)
	$(call log_info,xray 已运行 [:$(XRAY_SOCKS_PORT)] — 跳过安装)
else
	@$(MAKE) --no-print-directory _install-xray
	@$(MAKE) --no-print-directory _configure-xray
endif

.PHONY: _install-xray
_install-xray:
	$(call log_info,安装 xray-core...)
	@bash $(SCRIPTS_DIR)/xray-install.sh install
	$(call log_info,xray-core 安装完成)

.PHONY: _configure-xray
_configure-xray:
	@if [ -z "$(XRAY_SUB_URL)" ]; then \
		echo -e "$(RED)[proxy-srv] 受限区域需要设置 XRAY_SUB_URL$(RESET)"; exit 1; \
	fi
	$(call log_info,拉取 xray 订阅并应用最优节点...)
	@python3 $(SCRIPTS_DIR)/xray-manager.py update "$(XRAY_SUB_URL)"
	$(call log_info,安装 xray watchdog timer...)
	@python3 $(SCRIPTS_DIR)/xray-manager.py install

# ── tor ───────────────────────────────────────────────────────────────────────
.PHONY: _ensure-tor
_ensure-tor:
ifeq ($(TOR_READY),true)
	$(call log_info,tor 已运行 [:$(TOR_SOCKS_PORT)] — 跳过安装)
else
	@$(MAKE) --no-print-directory _install-tor
endif

.PHONY: _install-tor
_install-tor:
	$(call log_info,安装 tor + lyrebird...)
	@UPSTREAM_PROXY="$(PROXY_HTTP)" bash $(SCRIPTS_DIR)/tor-install.sh

# ── apply-torrc（受限区域：让 tor 走 xray 上游）──────────────────────────────
.PHONY: _apply-torrc
_apply-torrc:
	$(call log_info,配置 tor 通过 xray 上游代理...)
	@cp /etc/tor/torrc /etc/tor/torrc.bak.$$(date +%s) 2>/dev/null || true
	@{ \
	  echo 'SocksPort $(TOR_SOCKS_PORT)'; \
	  echo 'ControlPort $(TOR_CONTROL_PORT)'; \
	  echo 'DataDirectory /var/lib/tor'; \
	  echo ''; \
	  echo 'MaxCircuitDirtiness 60'; \
	  echo 'NewCircuitPeriod 30'; \
	  echo 'ClientOnly 1'; \
	  echo 'AvoidDiskWrites 1'; \
	  echo ''; \
	  echo '# xray HTTP proxy 作为 tor 上游'; \
	  echo 'HTTPSProxy 127.0.0.1:$(XRAY_HTTP_PORT)'; \
	  echo ''; \
	  echo 'UseBridges 1'; \
	  echo 'ClientTransportPlugin webtunnel exec /usr/local/bin/lyrebird'; \
	  echo ''; \
	  echo 'Bridge webtunnel [2001:db8:43cc:d277:5ba1:dcd1:516e:d983]:443 AD62C15FAC9C8695F41F4BB5D1F16373F906177F url=https://mitch.pmvl.eu/r9mZqSFwOHSQATtQoPWwZQk9 version=0.0.1'; \
	  echo ''; \
	  echo 'Log info'; \
	} > /etc/tor/torrc
	@sudo -u debian-tor tor --verify-config -f /etc/tor/torrc
	@systemctl restart tor@default
	$(call log_info,torrc 配置完成)

# ── 运维 targets ──────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall:                        ## 卸载代理层
	$(call require_root)
	@$(call systemd_disable_stop,tor@default)
	@$(call systemd_disable_stop,xray)
	@$(call systemd_disable_stop,xray-watchdog.timer)
	@rm -f /usr/local/bin/xray /usr/local/bin/lyrebird
	$(call log_info,proxy-srv 已卸载)

.PHONY: status
status:                           ## 显示代理状态
	@printf "  %-10s " "xray:"
	@systemctl is-active xray 2>/dev/null || echo "inactive"
	@printf "  %-10s " "tor:"
	@systemctl is-active tor@default 2>/dev/null || echo "inactive"
	@echo "  xray socks5 :$(XRAY_SOCKS_PORT)  → $(shell nc -z 127.0.0.1 $(XRAY_SOCKS_PORT) 2>/dev/null && echo reachable || echo unreachable)"
	@echo "  tor  socks5 :$(TOR_SOCKS_PORT)   → $(shell nc -z 127.0.0.1 $(TOR_SOCKS_PORT) 2>/dev/null && echo reachable || echo unreachable)"

.PHONY: test
test:                             ## 健康检查
ifeq ($(RESTRICTED_REGION),true)
	@nc -z 127.0.0.1 $(XRAY_SOCKS_PORT) 2>/dev/null \
		|| { echo "xray socks5 :$(XRAY_SOCKS_PORT) 不可达"; exit 1; }
endif
	@nc -z 127.0.0.1 $(TOR_SOCKS_PORT) 2>/dev/null \
		|| { echo "tor socks5 :$(TOR_SOCKS_PORT) 不可达"; exit 1; }

.PHONY: xray-update
xray-update:                      ## 更新 xray 订阅节点
	@python3 $(SCRIPTS_DIR)/xray-manager.py update "$(XRAY_SUB_URL)"

.PHONY: xray-status
xray-status:                      ## 查看 xray 当前节点和延迟
	@python3 $(SCRIPTS_DIR)/xray-manager.py status

.PHONY: clean
clean:
	@rm -f /tmp/xray-*.zip /tmp/tor-*.tar.gz

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
