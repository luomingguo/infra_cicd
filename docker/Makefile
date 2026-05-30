# =============================================================================
# docker/Makefile
# =============================================================================
include ../common.mk

MODULE_NAME := docker

.DEFAULT_GOAL := install

.PHONY: install
install: _check-root              ## 安装 Docker Engine + compose-plugin
	@if command -v docker &>/dev/null; then \
		echo -e "$(GREEN)[docker]$(RESET) 已安装: $$(docker --version)"; \
	else \
		$(MAKE) --no-print-directory _install-engine; \
	fi
ifeq ($(RESTRICTED_REGION),true)
	@$(MAKE) --no-print-directory _configure-proxy
endif

.PHONY: _install-engine
_install-engine:
ifeq ($(RESTRICTED_REGION),true)
	$(call log_info,受限区域：通过代理安装 Docker...)
	@bash install.sh
else
	$(call log_info,直接安装 Docker...)
	@$(CURL) https://get.docker.com | sh
	@systemctl enable --now docker
endif
	$(call log_info,Docker $$(docker --version) 安装完成)

.PHONY: _configure-proxy
_configure-proxy:
	$(call log_info,配置 Docker daemon 代理...)
	@bash docker_proxy.sh

.PHONY: uninstall
uninstall: _check-root            ## 卸载 Docker（不删除数据卷）
	@apt-get remove -y docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin 2>/dev/null || true
	$(call log_info,Docker 已卸载（数据卷保留在 /var/lib/docker）)

.PHONY: status
status:                           ## 显示 Docker 服务状态
	@systemctl status docker --no-pager -l -n 5 2>/dev/null || echo "  (未运行)"
	@echo
	@docker info 2>/dev/null | grep -E 'Server Version|Containers:|Images:' || true

.PHONY: test
test:                             ## 健康检查：docker info
	@docker info &>/dev/null || { echo "Docker daemon 不可达"; exit 1; }
	@docker compose version &>/dev/null || { echo "compose-plugin 未安装"; exit 1; }

.PHONY: clean
clean:                            ## 清理未使用的镜像和容器
	@docker system prune -f 2>/dev/null || true

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[0;36m%-18s\033[0m %s\n", $$1, $$2}'
