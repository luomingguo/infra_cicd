# =============================================================================
# k8s/Makefile
# 兼容 k3s / kind / vanilla k8s
# manifests/ 由 config-gen.py 生成，此文件只做生命周期管理
# =============================================================================
include ../common.mk

MODULE_NAME  := k8s
MANIFESTS    := manifests
KUBECTL      := kubectl
NS           := $(K8S_NAMESPACE)

.DEFAULT_GOAL := install

# ── 安装 k8s runtime（按 flavor）──────────────────────────────────────────────
.PHONY: install-runtime
install-runtime: _check-root      ## 安装 k8s runtime（k3s/kind，按 config.yaml 中的 flavor）
ifeq ($(K8S_FLAVOR),k3s)
	@$(MAKE) --no-print-directory _install-k3s
else ifeq ($(K8S_FLAVOR),kind)
	@$(MAKE) --no-print-directory _install-kind
else
	$(call log_info,flavor=$(K8S_FLAVOR)，假设 kubectl 已就绪，跳过 runtime 安装)
endif

.PHONY: _install-k3s
_install-k3s:
	$(call log_info,安装 k3s...)
	@command -v k3s &>/dev/null && { $(call log_info,k3s 已安装，跳过); exit 0; }; \
	INSTALL_K3S_EXEC="--disable traefik" \
	$(if $(PROXY_HTTP),HTTPS_PROXY=$(PROXY_HTTP) HTTP_PROXY=$(PROXY_HTTP),) \
	bash <($(CURL) https://get.k3s.io)
	@mkdir -p $$HOME/.kube
	@cp /etc/rancher/k3s/k3s.yaml $$HOME/.kube/config
	@chmod 600 $$HOME/.kube/config
	$(call wait_port,6443,k3s apiserver,60)

.PHONY: _install-kind
_install-kind:
	$(call log_info,安装 kind + 创建集群...)
	@command -v kind &>/dev/null || { \
		$(CURL) https://kind.sigs.k8s.io/dl/latest/kind-linux-$(ARCH) -o /usr/local/bin/kind; \
		chmod +x /usr/local/bin/kind; \
	}
	@kind get clusters 2>/dev/null | grep -q infra || \
		kind create cluster --name infra --config $(CURDIR)/kind-config.yaml
	@kind get kubeconfig --name infra > $$HOME/.kube/config
	$(call log_info,kind 集群已就绪)

# ── 部署 manifests ────────────────────────────────────────────────────────────
.PHONY: install
install: _check-manifests _create-namespace _apply-secrets _apply  ## 部署 k8s manifests
	$(call log_info,等待 Pod 就绪...)
	@$(KUBECTL) rollout status statefulset/etcd   -n $(NS) --timeout=120s || true
	@$(KUBECTL) rollout status deployment/prometheus -n $(NS) --timeout=120s || true
	@$(KUBECTL) rollout status deployment/grafana    -n $(NS) --timeout=120s || true
	$(call log_info,k8s 部署完成)

.PHONY: _check-manifests
_check-manifests:
	@[ -d $(MANIFESTS) ] || { \
		echo -e "$(RED)manifests/ 不存在，请先运行 make config-gen$(RESET)"; exit 1; \
	}
	@command -v kubectl &>/dev/null || { \
		echo -e "$(RED)未找到 kubectl，请先运行 make install-runtime$(RESET)"; exit 1; \
	}

.PHONY: _create-namespace
_create-namespace:
	@$(KUBECTL) apply -f $(MANIFESTS)/00-namespace.yaml

.PHONY: _apply-secrets
_apply-secrets:
	@$(KUBECTL) create secret generic grafana-secret \
		--from-literal=admin-password="$${GRAFANA_ADMIN_PASSWORD:-changeme}" \
		--namespace=$(NS) \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -

.PHONY: _apply
_apply:
	@$(KUBECTL) apply -k $(MANIFESTS)/

# ── 运维 ──────────────────────────────────────────────────────────────────────
.PHONY: uninstall
uninstall: _check-root            ## 删除所有 k8s 资源（保留 PVC 数据）
	@$(KUBECTL) delete namespace $(NS) --ignore-not-found
	$(call log_warn,PVC 数据已保留，手动删除: kubectl delete pvc --all -n $(NS))

.PHONY: status
status:                           ## 查看 Pod 状态
	@$(KUBECTL) get pods,svc,pvc -n $(NS) 2>/dev/null || echo "  (namespace 不存在)"

.PHONY: test
test:                             ## 健康检查
	@$(KUBECTL) get pods -n $(NS) --field-selector=status.phase!=Running \
		--no-headers 2>/dev/null | grep -v "Completed" \
		| { read line; [ -z "$$line" ] || { echo "有 Pod 未就绪: $$line"; exit 1; }; }
	$(call log_info,所有 Pod 运行正常 ✓)

.PHONY: logs
logs:                             ## 查看所有 Pod 日志（需要 stern，否则用 kubectl）
	@command -v stern &>/dev/null \
		&& stern -n $(NS) . \
		|| $(KUBECTL) logs -n $(NS) -l 'app in (etcd,prometheus,grafana)' --prefix --tail=50

.PHONY: port-forward
port-forward:                     ## 本地端口转发（开发调试用）
	@echo "转发中... Ctrl+C 退出"
	@$(KUBECTL) port-forward -n $(NS) svc/prometheus $(PROMETHEUS_PORT):$(PROMETHEUS_PORT) &
	@$(KUBECTL) port-forward -n $(NS) svc/grafana    $(GRAFANA_PORT):$(GRAFANA_PORT) &
	@$(KUBECTL) port-forward -n $(NS) svc/etcd-client $(ETCD_CLIENT_PORT):$(ETCD_CLIENT_PORT) &
	@echo "Prometheus : http://localhost:$(PROMETHEUS_PORT)"
	@echo "Grafana    : http://localhost:$(GRAFANA_PORT)"
	@wait

.PHONY: diff
diff:                             ## 预览 manifest 变更（不实际应用）
	@$(KUBECTL) diff -k $(MANIFESTS)/ || true

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*##"};{printf "  \033[0;36m%-22s\033[0m %s\n",$$1,$$2}'
