# =============================================================================
# common.mk — 子模块共用工具层
# 所有配置变量由根 Makefile 从 config.mk 导出，此处只定义工具函数
# =============================================================================

SHELL := /bin/bash

# ── 颜色 ──────────────────────────────────────────────────────────────────────
BOLD   := \033[1m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
CYAN   := \033[0;36m
RESET  := \033[0m

# MODULE_NAME 由各子模块 Makefile 定义
log_info  = @echo -e "$(GREEN)[$(MODULE_NAME)]$(RESET) $(1)"
log_warn  = @echo -e "$(YELLOW)[$(MODULE_NAME)]$(RESET) $(1)"
log_error = @echo -e "$(RED)[$(MODULE_NAME)]$(RESET) $(1)" >&2

# ── 架构检测 ──────────────────────────────────────────────────────────────────
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_M),x86_64)
  ARCH := amd64
else ifeq ($(UNAME_M),aarch64)
  ARCH := arm64
else
  $(error 不支持的架构: $(UNAME_M))
endif

# ── 网络工具（代理由根 Makefile 通过环境变量导出）────────────────────────────
# PROXY_HTTP 已由根 Makefile export，此处直接使用
CURL_PROXY    := $(if $(PROXY_HTTP),-x $(PROXY_HTTP),)
CURL          := curl -fsSL $(CURL_PROXY)

APT_PROXY_OPTS := $(if $(PROXY_HTTP),\
  -o Acquire::http::Proxy="$(PROXY_HTTP)" \
  -o Acquire::https::Proxy="$(PROXY_HTTP)",)
APT := apt-get $(APT_PROXY_OPTS)

# ── systemd 操作 ──────────────────────────────────────────────────────────────
define systemd_enable_start
	systemctl daemon-reload
	systemctl enable $(1)
	systemctl restart $(1)
endef

define systemd_disable_stop
	systemctl disable --now $(1) 2>/dev/null || true
endef

# ── 等待端口就绪 ──────────────────────────────────────────────────────────────
# 用法：$(call wait_port,2379,etcd,30)
define wait_port
	@printf "  等待 $(2) :$(1) 就绪"; \
	for i in $$(seq 1 $(3)); do \
		nc -z 127.0.0.1 $(1) 2>/dev/null && echo " ✓" && exit 0 || true; \
		sleep 1; printf "."; \
	done; echo " 超时"; exit 1
endef

# ── 通用检查 ──────────────────────────────────────────────────────────────────
.PHONY: _check-root
_check-root:
	@[ "$$(id -u)" -eq 0 ] || { echo -e "$(RED)需要 root 权限$(RESET)"; exit 1; }

# 每个子模块独立运行时（不通过根 Makefile），加载 config.mk
_maybe_load_config:
	@[ -n "$(ETCD_VERSION)" ] || { \
		echo -e "$(YELLOW)直接调用子模块，尝试加载 ../config.mk$(RESET)"; \
		[ -f ../config.mk ] || { echo -e "$(RED)找不到 ../config.mk，请先运行 make config-gen$(RESET)"; exit 1; }; \
	}
