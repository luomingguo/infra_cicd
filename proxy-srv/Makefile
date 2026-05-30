# =============================================================================
# proxy-srv/Makefile
# 受限区域：xray-core + tor + lyrebird
# 非受限区域：仅 tor + lyrebird
# =============================================================================
include ../common.mk

MODULE_NAME  := proxy-srv
XRAY_SUB_URL ?=

.DEFAULT_GOAL := install

.PHONY: install
install: _check-root              ## 安装代理层（自动判断 xray 或仅 tor）
	@echo -e "$(CYAN)[proxy-srv]$(RESET) RESTRICTED_REGION=$(RESTRICTED_REGION)"
ifeq ($(RESTRICTED_REGION),true)
	@$(MAKE) --no-print-directory _install-xray
	@$(MAKE) --no-print-directory _configure-xray
endif
	@$(MAKE) --no-print-directory _install-tor
ifeq ($(RESTRICTED_REGION),true)
	@$(MAKE) --no-print-directory _apply-torrc
endif

# ── xray ──────────────────────────────────────────────────────────────────────
.PHONY: _install-xray
_install-xray:
	$(call log_info,安装 xray-core...)
	@bash install-release.sh install
	$(call log_info,xray-core 安装完成)

.PHONY: _configure-xray
_configure-xray:
	@if [ -z "$(XRAY_SUB_URL)" ]; then \
		echo -e "$(RED)[proxy-srv] 受限区域需要设置 XRAY_SUB_URL$(RESET)"; exit 1; \
	fi
	$(call log_info,拉取 xray 订阅并应用最优节点...)
	@python3 xray-manager.py update "$(XRAY_SUB_URL)"
	$(call log_info,安装 xray watchdog timer...)
	@python3 xray-manager.py install

# ── tor ───────────────────────────────────────────────────────────────────────
.PHONY: _install-tor
_install-tor:
	$(call log_info,安装 tor + lyrebird...)
	@UPSTREAM_PROXY="$(PROXY_HTTP)" bash tor_install.sh

.PHONY: _apply-torrc
_apply-torrc:
	$(call log_info,配置 tor 通过 xray 上游代理...)
	@bash apply_torrc.sh

# ── 运维 targets ──────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall: _check-root            ## 卸载代理层
	$(call systemd_disable_stop,tor@default)
	$(call systemd_disable_stop,xray)
	$(call systemd_disable_stop,xray-watchdog.timer)
	@rm -f /usr/local/bin/xray /usr/local/bin/lyrebird
	$(call log_info,proxy-srv 已卸载)

.PHONY: status
status:                           ## 显示代理服务状态
	@echo "── xray ──"
	@systemctl is-active xray 2>/dev/null \
		&& systemctl status xray --no-pager -l -n 5 \
		|| echo "  (未安装或未运行)"
	@echo "── tor ──"
	@systemctl status tor@default --no-pager -l -n 5 2>/dev/null || echo "  (未运行)"

.PHONY: test
test:                             ## 健康检查：验证出口 IP 可达
ifeq ($(RESTRICTED_REGION),true)
	@curl --silent --max-time 10 --socks5 127.0.0.1:10808 \
		http://ip-api.com/json 2>/dev/null | python3 -m json.tool | grep '"query"' \
		|| { echo "xray socks5 不可达"; exit 1; }
endif
	@curl --silent --max-time 15 --socks5 127.0.0.1:9050 \
		http://ip-api.com/json 2>/dev/null | python3 -m json.tool | grep '"query"' \
		|| { echo "tor socks5 不可达"; exit 1; }

.PHONY: xray-update
xray-update:                      ## 更新 xray 订阅节点
	@python3 xray-manager.py update "$(XRAY_SUB_URL)"

.PHONY: xray-status
xray-status:                      ## 查看 xray 当前节点状态
	@python3 xray-manager.py status

.PHONY: clean
clean:                            ## 清理临时文件
	@rm -f /tmp/xray-*.zip /tmp/tor-*.tar.gz

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
