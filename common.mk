# =============================================================================
# common.mk — 子模块共用工具层
# 颜色变量、日志宏、require_root、CURL、APT 的唯一定义处
# 负责加载 config.mk 和 runtime.mk，子模块无需重复 include
# =============================================================================

SHELL := /bin/bash

# ── 自动加载配置（子模块直接调用时生效，根 Makefile 已加载则跳过）──────────────
ifndef DEPLOY_MODE
  ifneq ($(wildcard $(INFRA_CONFIG_MK)),)
    include $(INFRA_CONFIG_MK)
  else ifneq ($(wildcard ../config.mk),)
    include ../config.mk
  endif
  ifneq ($(wildcard $(INFRA_RUNTIME_MK)),)
    include $(INFRA_RUNTIME_MK)
  else ifneq ($(wildcard ../runtime.mk),)
    include ../runtime.mk
  endif
endif

# ── 脚本目录（从 config.mk 路径推导或回退到相对路径）────────────────────────
SCRIPTS_DIR := $(if $(INFRA_CONFIG_MK),$(dir $(INFRA_CONFIG_MK))scripts,../scripts)

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
else ifeq ($(UNAME_M),arm64)
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

# ── 权限检查（在 recipe 内联调用：$(call require_root)）────────────────────────
define require_root
@[ "$$(id -u)" -eq 0 ] || { echo -e "$(RED)需要 root 权限$(RESET)"; exit 1; }
endef

# 保留 _check-root 作为兼容别名
.PHONY: _check-root
_check-root:
	$(call require_root)
