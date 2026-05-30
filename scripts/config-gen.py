#!/usr/bin/env python3
"""
scripts/config-gen.py
从 config.yaml 生成：
  - config.mk              → 被所有 Makefile include
  - docker/compose/        → docker-compose.yml（compose 模式）
  - k8s/manifests/         → k8s YAML（k8s 模式）

用法：
    python3 scripts/config-gen.py            # 全量生成
    python3 scripts/config-gen.py --check    # 仅校验
    python3 scripts/config-gen.py --diff     # 预览 config.mk 变更
    python3 scripts/config-gen.py --target compose   # 只生成 compose
    python3 scripts/config-gen.py --target k8s       # 只生成 k8s
"""

import sys, os, argparse, difflib, textwrap
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    os.system("pip3 install pyyaml --break-system-packages -q")
    import yaml

REPO_ROOT = Path(__file__).parent.parent
CONFIG_IN = REPO_ROOT / "config.yaml"
CONFIG_MK = REPO_ROOT / "config.mk"

# ── 校验 ──────────────────────────────────────────────────────────────────────

def validate(cfg: dict) -> list[str]:
    errors = []
    for section, key in [
        ("deploy", "mode"), ("deploy", "order"),
        ("versions", "etcd"), ("versions", "prometheus"), ("versions", "grafana"),
        ("etcd", "client_port"), ("prometheus", "port"), ("grafana", "port"),
    ]:
        if section not in cfg or key not in cfg[section]:
            errors.append(f"缺少必填字段: {section}.{key}")

    mode = cfg.get("deploy", {}).get("mode", "")
    if mode not in {"compose", "k8s"}:
        errors.append(f"deploy.mode 必须是 compose 或 k8s，当前: {mode!r}")

    network = cfg.get("deploy", {}).get("network", "")
    if network not in {"auto", "restricted", "open"}:
        errors.append(f"deploy.network 必须是 auto/restricted/open，当前: {network!r}")

    # 端口冲突
    ports: dict[int, str] = {}
    for name, port in {
        "proxy.xray.socks_port":  cfg.get("proxy",{}).get("xray",{}).get("socks_port"),
        "proxy.xray.http_port":   cfg.get("proxy",{}).get("xray",{}).get("http_port"),
        "proxy.tor.socks_port":   cfg.get("proxy",{}).get("tor",{}).get("socks_port"),
        "etcd.client_port":       cfg.get("etcd",{}).get("client_port"),
        "etcd.peer_port":         cfg.get("etcd",{}).get("peer_port"),
        "prometheus.port":        cfg.get("prometheus",{}).get("port"),
        "grafana.port":           cfg.get("grafana",{}).get("port"),
    }.items():
        if port is None: continue
        if port in ports:
            errors.append(f"端口冲突: {port} 被 {ports[port]} 和 {name} 同时使用")
        ports[port] = name

    if not cfg.get("etcd", {}).get("nodes"):
        errors.append("etcd.nodes 不能为空")

    return errors

# ── config.mk 生成 ────────────────────────────────────────────────────────────

def build_initial_cluster(nodes, peer_port):
    return ",".join(f"{n['name']}=http://{n['ip']}:{peer_port}" for n in nodes)

def generate_mk(cfg: dict) -> str:
    deploy   = cfg["deploy"]
    versions = cfg["versions"]
    proxy    = cfg.get("proxy", {})
    etcd     = cfg["etcd"]
    prom     = cfg["prometheus"]
    graf     = cfg["grafana"]
    certs    = cfg.get("certs", {})
    nodes    = etcd.get("nodes", [])
    xray     = proxy.get("xray", {})
    tor      = proxy.get("tor", {})

    lines = [
        "# 自动生成，请勿手动编辑。修改 config.yaml 后运行 make config-gen",
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "# ── 部署模式 ────────────────────────────────────────────────",
        f"DEPLOY_MODE           := {deploy.get('mode','compose')}",
        f"DEPLOY_MODULES        := {' '.join(deploy.get('order',[]))}",
        f"DEPLOY_NETWORK        := {deploy.get('network','auto')}",
        f"DEPLOY_HOST_IP        := {deploy.get('host_ip','127.0.0.1')}",
        f"DEPLOY_DOMAIN         := {deploy.get('domain','')}",
        "",
        "# ── 证书 ────────────────────────────────────────────────────",
        f"CERTS_DIR             := {certs.get('dir','./certs')}",
        f"CERTS_FULLCHAIN       := {certs.get('fullchain','./certs/fullchain.pem')}",
        f"CERTS_PRIVKEY         := {certs.get('privkey','./certs/privkey.pem')}",
        "",
        "# ── 版本 ────────────────────────────────────────────────────",
        f"VERSION_ETCD          := {versions.get('etcd','3.6.0')}",
        f"VERSION_PROMETHEUS    := {versions.get('prometheus','3.8.0')}",
        f"VERSION_NODE_EXPORTER := {versions.get('node_exporter','1.8.2')}",
        f"VERSION_GRAFANA       := {versions.get('grafana','11.5.0')}",
        "",
        "# ── 代理 ────────────────────────────────────────────────────",
        f"XRAY_SOCKS_PORT       := {xray.get('socks_port',10808)}",
        f"XRAY_HTTP_PORT        := {xray.get('http_port',10809)}",
        f"TOR_SOCKS_PORT        := {tor.get('socks_port',9050)}",
        f"TOR_CONTROL_PORT      := {tor.get('control_port',9051)}",
        f"PROXY_HTTP_ADDR       := http://127.0.0.1:{xray.get('http_port',10809)}",
        f"PROXY_SOCKS5_ADDR     := socks5://127.0.0.1:{xray.get('socks_port',10808)}",
        "",
        "# ── etcd ────────────────────────────────────────────────────",
        f"ETCD_VERSION          := {versions.get('etcd','3.6.0')}",
        f"ETCD_CLIENT_PORT      := {etcd.get('client_port',2379)}",
        f"ETCD_PEER_PORT        := {etcd.get('peer_port',2380)}",
        f"ETCD_DATA_DIR         := {cfg.get('storage',{}).get('host',{}).get('etcd','/var/lib/etcd')}",
        f"ETCD_NODE_NAME        := {nodes[0]['name'] if nodes else 'etcd-0'}",
        f"ETCD_NODE_IP          := {nodes[0]['ip'] if nodes else '127.0.0.1'}",
        f"ETCD_NODE_COUNT       := {len(nodes)}",
        f"ETCD_INITIAL_CLUSTER  := {build_initial_cluster(nodes, etcd.get('peer_port',2380))}",
        f"ETCD_RETENTION        := {etcd.get('retention','1h')}",
        "",
        "# ── Prometheus ──────────────────────────────────────────────",
        f"PROMETHEUS_VERSION    := {versions.get('prometheus','3.8.0')}",
        f"PROMETHEUS_PORT       := {prom.get('port',9090)}",
        f"PROMETHEUS_DATA_DIR   := {cfg.get('storage',{}).get('host',{}).get('prometheus','/var/lib/prometheus')}",
        f"PROMETHEUS_RETENTION  := {prom.get('retention_time','30d')}",
        f"PROMETHEUS_RET_SIZE   := {prom.get('retention_size','10GB')}",
        f"PROMETHEUS_SCRAPE_INT := {prom.get('scrape_interval','15s')}",
        "",
        "# ── Grafana ─────────────────────────────────────────────────",
        f"GRAFANA_VERSION       := {versions.get('grafana','11.5.0')}",
        f"GRAFANA_PORT          := {graf.get('port',3000)}",
        f"GRAFANA_DOMAIN        := {graf.get('domain','') or deploy.get('domain','')}",
        f"GRAFANA_TLS           := {str(graf.get('tls',False)).lower()}",
        f"GRAFANA_DATA_DIR      := {cfg.get('storage',{}).get('host',{}).get('grafana','/var/lib/grafana')}",
        "",
        "# ── compose 专属 ─────────────────────────────────────────────",
        f"COMPOSE_PROJECT       := {cfg.get('compose',{}).get('project_name','infra')}",
        f"COMPOSE_NETWORK       := {cfg.get('compose',{}).get('network_name','infra-net')}",
        f"COMPOSE_RESTART       := {cfg.get('compose',{}).get('restart','unless-stopped')}",
        "",
        "# ── k8s 专属 ─────────────────────────────────────────────────",
        f"K8S_NAMESPACE         := {cfg.get('k8s',{}).get('namespace','infra')}",
        f"K8S_FLAVOR            := {cfg.get('k8s',{}).get('flavor','k3s')}",
        f"K8S_STORAGE_CLASS     := {cfg.get('k8s',{}).get('storage_class','')}",
        f"K8S_ETCD_PVC_SIZE     := {cfg.get('storage',{}).get('k8s',{}).get('etcd_size','8Gi')}",
        f"K8S_PROM_PVC_SIZE     := {cfg.get('storage',{}).get('k8s',{}).get('prometheus_size','20Gi')}",
        f"K8S_GRAFANA_PVC_SIZE  := {cfg.get('storage',{}).get('k8s',{}).get('grafana_size','2Gi')}",
        f"K8S_IMAGE_PULL_POLICY := {cfg.get('k8s',{}).get('image_pull_policy','IfNotPresent')}",
    ]

    fw = cfg.get("firewall", {}).get("allow_ports", [])
    if fw:
        lines += [
            "",
            "# ── 防火墙 ──────────────────────────────────────────────",
            f"FIREWALL_ALL_PORTS    := {' '.join(str(r['port']) for r in fw)}",
            f"FIREWALL_PUBLIC_PORTS := {' '.join(str(r['port']) for r in fw if not r.get('internal_only'))}",
        ]

    return "\n".join(lines) + "\n"

# ── docker-compose.yml 生成 ───────────────────────────────────────────────────

def generate_compose(cfg: dict) -> str:
    versions = cfg["versions"]
    etcd     = cfg["etcd"]
    prom     = cfg["prometheus"]
    graf     = cfg["grafana"]
    storage  = cfg.get("storage", {}).get("host", {})
    compose  = cfg.get("compose", {})
    nodes    = etcd.get("nodes", [])
    restart  = compose.get("restart", "unless-stopped")
    net      = compose.get("network_name", "infra-net")
    proj     = compose.get("project_name", "infra")

    # etcd 单节点 vs 多节点
    initial_cluster = ",".join(
        f"{n['name']}=http://{n['name']}:{etcd.get('peer_port',2380)}"
        for n in nodes
    )

    etcd_services = {}
    for i, node in enumerate(nodes):
        svc = {
            "image": f"quay.io/coreos/etcd:v{versions.get('etcd','3.6.0')}",
            "container_name": node["name"],
            "restart": restart,
            "networks": [net],
            "volumes": [f"{storage.get('etcd','/var/lib/etcd')}/{node['name']}:/etcd-data"],
            "environment": [
                f"ETCD_NAME={node['name']}",
                f"ETCD_DATA_DIR=/etcd-data",
                f"ETCD_LISTEN_CLIENT_URLS=http://0.0.0.0:{etcd.get('client_port',2379)}",
                f"ETCD_ADVERTISE_CLIENT_URLS=http://{node['name']}:{etcd.get('client_port',2379)}",
                f"ETCD_LISTEN_PEER_URLS=http://0.0.0.0:{etcd.get('peer_port',2380)}",
                f"ETCD_INITIAL_ADVERTISE_PEER_URLS=http://{node['name']}:{etcd.get('peer_port',2380)}",
                f"ETCD_INITIAL_CLUSTER={initial_cluster}",
                f"ETCD_INITIAL_CLUSTER_TOKEN=infra-etcd-cluster",
                f"ETCD_INITIAL_CLUSTER_STATE=new",
                f"ETCD_AUTO_COMPACTION_MODE=periodic",
                f"ETCD_AUTO_COMPACTION_RETENTION={etcd.get('retention','1h')}",
            ],
        }
        # 只有第一个节点对外暴露端口（单机访问点）
        if i == 0:
            svc["ports"] = [
                f"{etcd.get('client_port',2379)}:{etcd.get('client_port',2379)}",
            ]
        etcd_services[node["name"]] = svc

    # etcd endpoints for prometheus scrape（container names joined）
    etcd_endpoints = ",".join(
        f"{n['name']}:{etcd.get('client_port',2379)}" for n in nodes
    )

    doc = {
        "name": proj,
        "services": {
            **etcd_services,
            "prometheus": {
                "image": f"prom/prometheus:v{versions.get('prometheus','3.8.0')}",
                "container_name": "prometheus",
                "restart": restart,
                "networks": [net],
                "ports": [f"{prom.get('port',9090)}:{prom.get('port',9090)}"],
                "volumes": [
                    f"{storage.get('prometheus','/var/lib/prometheus')}:/prometheus",
                    "./templates/compose/prometheus.yml:/etc/prometheus/prometheus.yml:ro",
                    "./templates/compose/prometheus-rules:/etc/prometheus/rules:ro",
                ],
                "command": [
                    "--config.file=/etc/prometheus/prometheus.yml",
                    f"--storage.tsdb.path=/prometheus",
                    f"--storage.tsdb.retention.time={prom.get('retention_time','30d')}",
                    f"--storage.tsdb.retention.size={prom.get('retention_size','10GB')}",
                    f"--web.listen-address=0.0.0.0:{prom.get('port',9090)}",
                    "--web.enable-lifecycle",
                ],
                "depends_on": list(etcd_services.keys()),
            },
            "node-exporter": {
                "image": f"prom/node-exporter:v{versions.get('node_exporter','1.8.2')}",
                "container_name": "node-exporter",
                "restart": restart,
                "networks": [net],
                "pid": "host",
                "volumes": [
                    "/proc:/host/proc:ro",
                    "/sys:/host/sys:ro",
                    "/:/rootfs:ro",
                ],
                "command": [
                    "--path.procfs=/host/proc",
                    "--path.sysfs=/host/sys",
                    "--collector.filesystem.ignored-mount-points=^/(sys|proc|dev|host|etc)($|/)",
                ],
            },
            "grafana": {
                "image": f"grafana/grafana:{versions.get('grafana','11.5.0')}",
                "container_name": "grafana",
                "restart": restart,
                "networks": [net],
                "ports": [f"{graf.get('port',3000)}:{graf.get('port',3000)}"],
                "volumes": [
                    f"{storage.get('grafana','/var/lib/grafana')}:/var/lib/grafana",
                    "./templates/compose/grafana-provisioning:/etc/grafana/provisioning:ro",
                ],
                "environment": [
                    f"GF_SERVER_HTTP_PORT={graf.get('port',3000)}",
                    "GF_USERS_ALLOW_SIGN_UP=false",
                    # 密码通过 secret/env 注入，不写死
                    "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}",
                ],
                "depends_on": ["prometheus"],
            },
        },
        "networks": {
            net: {"driver": "bridge"},
        },
        "volumes": {},   # named volumes 可选，此处使用 host bind mount
    }

    return yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)

# ── k8s manifests 生成 ────────────────────────────────────────────────────────

def generate_k8s_manifests(cfg: dict) -> dict[str, str]:
    """返回 {filename: yaml_content} 字典"""
    versions = cfg["versions"]
    etcd     = cfg["etcd"]
    prom     = cfg["prometheus"]
    graf     = cfg["grafana"]
    k8s      = cfg.get("k8s", {})
    storage  = cfg.get("storage", {}).get("k8s", {})
    nodes    = etcd.get("nodes", [])
    ns       = k8s.get("namespace", "infra")
    sc       = k8s.get("storage_class", "") or None
    ipp      = k8s.get("image_pull_policy", "IfNotPresent")
    res      = k8s.get("resources", {})

    files: dict[str, str] = {}

    # ── namespace ─────────────────────────────────────────────────────────────
    files["00-namespace.yaml"] = yaml.dump({
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": ns, "labels": {"app.kubernetes.io/managed-by": "infra_cicd"}},
    }, allow_unicode=True)

    # ── etcd StatefulSet ──────────────────────────────────────────────────────
    etcd_replicas = len(nodes)
    etcd_res = res.get("etcd", {})
    initial_cluster = ",".join(
        f"etcd-{{{{.index}}}}=http://etcd-{{{{.index}}}}.etcd-headless.{ns}.svc.cluster.local"
        f":{etcd.get('peer_port',2380)}"
        for _ in nodes
    )
    # 用真实编号替换模板占位
    initial_cluster_real = ",".join(
        f"etcd-{i}=http://etcd-{i}.etcd-headless.{ns}.svc.cluster.local:{etcd.get('peer_port',2380)}"
        for i in range(etcd_replicas)
    )

    etcd_sts = {
        "apiVersion": "apps/v1", "kind": "StatefulSet",
        "metadata": {"name": "etcd", "namespace": ns},
        "spec": {
            "serviceName": "etcd-headless",
            "replicas": etcd_replicas,
            "selector": {"matchLabels": {"app": "etcd"}},
            "template": {
                "metadata": {"labels": {"app": "etcd"}},
                "spec": {
                    "containers": [{
                        "name": "etcd",
                        "image": f"quay.io/coreos/etcd:v{versions.get('etcd','3.6.0')}",
                        "imagePullPolicy": ipp,
                        "ports": [
                            {"containerPort": etcd.get("client_port",2379), "name": "client"},
                            {"containerPort": etcd.get("peer_port",2380),   "name": "peer"},
                        ],
                        "env": [
                            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
                            {"name": "POD_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}},
                            {"name": "ETCD_NAME", "value": "$(POD_NAME)"},
                            {"name": "ETCD_DATA_DIR", "value": "/var/lib/etcd"},
                            {"name": "ETCD_LISTEN_CLIENT_URLS",
                             "value": f"http://0.0.0.0:{etcd.get('client_port',2379)}"},
                            {"name": "ETCD_ADVERTISE_CLIENT_URLS",
                             "value": f"http://$(POD_NAME).etcd-headless.$(POD_NAMESPACE).svc.cluster.local:{etcd.get('client_port',2379)}"},
                            {"name": "ETCD_LISTEN_PEER_URLS",
                             "value": f"http://0.0.0.0:{etcd.get('peer_port',2380)}"},
                            {"name": "ETCD_INITIAL_ADVERTISE_PEER_URLS",
                             "value": f"http://$(POD_NAME).etcd-headless.$(POD_NAMESPACE).svc.cluster.local:{etcd.get('peer_port',2380)}"},
                            {"name": "ETCD_INITIAL_CLUSTER", "value": initial_cluster_real},
                            {"name": "ETCD_INITIAL_CLUSTER_TOKEN", "value": "infra-etcd-cluster"},
                            {"name": "ETCD_INITIAL_CLUSTER_STATE", "value": "new"},
                            {"name": "ETCD_AUTO_COMPACTION_MODE", "value": "periodic"},
                            {"name": "ETCD_AUTO_COMPACTION_RETENTION", "value": etcd.get("retention","1h")},
                        ],
                        "volumeMounts": [{"name": "etcd-data", "mountPath": "/var/lib/etcd"}],
                        "resources": etcd_res,
                        "readinessProbe": {
                            "exec": {"command": ["etcdctl", "endpoint", "health"]},
                            "initialDelaySeconds": 10, "periodSeconds": 5,
                        },
                    }],
                },
            },
            "volumeClaimTemplates": [{
                "metadata": {"name": "etcd-data"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": storage.get("etcd_size","8Gi")}},
                    **({"storageClassName": sc} if sc else {}),
                },
            }],
        },
    }
    etcd_headless_svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": "etcd-headless", "namespace": ns},
        "spec": {
            "clusterIP": "None",
            "selector": {"app": "etcd"},
            "ports": [
                {"name": "client", "port": etcd.get("client_port",2379)},
                {"name": "peer",   "port": etcd.get("peer_port",2380)},
            ],
        },
    }
    etcd_client_svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": "etcd-client", "namespace": ns},
        "spec": {
            "selector": {"app": "etcd"},
            "ports": [{"name": "client", "port": etcd.get("client_port",2379)}],
        },
    }
    files["10-etcd.yaml"] = "---\n".join([
        yaml.dump(etcd_sts, allow_unicode=True, sort_keys=False),
        yaml.dump(etcd_headless_svc, allow_unicode=True, sort_keys=False),
        yaml.dump(etcd_client_svc, allow_unicode=True, sort_keys=False),
    ])

    # ── Prometheus ────────────────────────────────────────────────────────────
    prom_res = res.get("prometheus", {})
    prom_deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "prometheus", "namespace": ns},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "prometheus"}},
            "template": {
                "metadata": {"labels": {"app": "prometheus"}},
                "spec": {
                    "securityContext": {"runAsUser": 65534, "fsGroup": 65534},
                    "containers": [{
                        "name": "prometheus",
                        "image": f"prom/prometheus:v{versions.get('prometheus','3.8.0')}",
                        "imagePullPolicy": ipp,
                        "args": [
                            "--config.file=/etc/prometheus/prometheus.yml",
                            "--storage.tsdb.path=/prometheus",
                            f"--storage.tsdb.retention.time={prom.get('retention_time','30d')}",
                            "--web.enable-lifecycle",
                        ],
                        "ports": [{"containerPort": prom.get("port",9090)}],
                        "volumeMounts": [
                            {"name": "config", "mountPath": "/etc/prometheus"},
                            {"name": "data",   "mountPath": "/prometheus"},
                        ],
                        "resources": prom_res,
                        "readinessProbe": {
                            "httpGet": {"path": "/-/ready", "port": prom.get("port",9090)},
                            "initialDelaySeconds": 10,
                        },
                    }],
                    "volumes": [
                        {"name": "config", "configMap": {"name": "prometheus-config"}},
                        {"name": "data",   "persistentVolumeClaim": {"claimName": "prometheus-data"}},
                    ],
                },
            },
        },
    }
    prom_svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": "prometheus", "namespace": ns},
        "spec": {
            "selector": {"app": "prometheus"},
            "ports": [{"port": prom.get("port",9090), "name": "web"}],
        },
    }
    prom_pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": "prometheus-data", "namespace": ns},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": storage.get("prometheus_size","20Gi")}},
            **({"storageClassName": sc} if sc else {}),
        },
    }
    files["20-prometheus.yaml"] = "---\n".join([
        yaml.dump(o, allow_unicode=True, sort_keys=False)
        for o in [prom_deploy, prom_svc, prom_pvc]
    ])

    # ── Grafana ───────────────────────────────────────────────────────────────
    graf_res = res.get("grafana", {})
    graf_deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "grafana", "namespace": ns},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "grafana"}},
            "template": {
                "metadata": {"labels": {"app": "grafana"}},
                "spec": {
                    "securityContext": {"runAsUser": 472, "fsGroup": 472},
                    "containers": [{
                        "name": "grafana",
                        "image": f"grafana/grafana:{versions.get('grafana','11.5.0')}",
                        "imagePullPolicy": ipp,
                        "ports": [{"containerPort": graf.get("port",3000)}],
                        "env": [
                            {"name": "GF_SERVER_HTTP_PORT", "value": str(graf.get("port",3000))},
                            {"name": "GF_USERS_ALLOW_SIGN_UP", "value": "false"},
                            {"name": "GF_SECURITY_ADMIN_PASSWORD",
                             "valueFrom": {"secretKeyRef": {"name": "grafana-secret", "key": "admin-password"}}},
                        ],
                        "volumeMounts": [
                            {"name": "data",          "mountPath": "/var/lib/grafana"},
                            {"name": "provisioning",  "mountPath": "/etc/grafana/provisioning"},
                        ],
                        "resources": graf_res,
                        "readinessProbe": {
                            "httpGet": {"path": "/api/health", "port": graf.get("port",3000)},
                            "initialDelaySeconds": 15,
                        },
                    }],
                    "volumes": [
                        {"name": "data",         "persistentVolumeClaim": {"claimName": "grafana-data"}},
                        {"name": "provisioning", "configMap": {"name": "grafana-provisioning"}},
                    ],
                },
            },
        },
    }
    graf_svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": "grafana", "namespace": ns},
        "spec": {
            "selector": {"app": "grafana"},
            "ports": [{"port": graf.get("port",3000), "name": "web"}],
            "type": "ClusterIP",
        },
    }
    graf_pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": "grafana-data", "namespace": ns},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": storage.get("grafana_size","2Gi")}},
            **({"storageClassName": sc} if sc else {}),
        },
    }
    files["30-grafana.yaml"] = "---\n".join([
        yaml.dump(o, allow_unicode=True, sort_keys=False)
        for o in [graf_deploy, graf_svc, graf_pvc]
    ])

    # ── kustomization.yaml（方便 kubectl apply -k）────────────────────────────
    files["kustomization.yaml"] = yaml.dump({
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "namespace": ns,
        "resources": [f for f in sorted(files.keys()) if f != "kustomization.yaml"],
    }, allow_unicode=True)

    return files

# ── 写文件工具 ────────────────────────────────────────────────────────────────

def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True

# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check",  action="store_true")
    parser.add_argument("--diff",   action="store_true")
    parser.add_argument("--target", choices=["mk", "compose", "k8s"], default=None,
                        help="只生成指定目标（默认全量）")
    parser.add_argument("--config", default=str(CONFIG_IN))
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    errors = validate(cfg)
    if errors:
        print("config.yaml 校验失败：", file=sys.stderr)
        for e in errors: print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        print(f"config.yaml 校验通过 ✓  mode={cfg['deploy']['mode']}")
        return

    mode = cfg["deploy"]["mode"]

    # config.mk
    if args.target in (None, "mk"):
        mk_content = generate_mk(cfg)
        if args.diff:
            old = CONFIG_MK.read_text() if CONFIG_MK.exists() else ""
            sys.stdout.writelines(difflib.unified_diff(
                old.splitlines(keepends=True),
                mk_content.splitlines(keepends=True),
                fromfile="config.mk (旧)", tofile="config.mk (新)",
            ))
            return
        changed = write_if_changed(CONFIG_MK, mk_content)
        print(f"{'✓ 已更新' if changed else '  无变化'} config.mk")

    # docker-compose.yml
    if args.target in (None, "compose") and mode == "compose":
        out = REPO_ROOT / "docker" / "compose" / "docker-compose.yml"
        changed = write_if_changed(out, generate_compose(cfg))
        print(f"{'✓ 已更新' if changed else '  无变化'} {out.relative_to(REPO_ROOT)}")

    # k8s manifests
    if args.target in (None, "k8s") and mode == "k8s":
        manifests = generate_k8s_manifests(cfg)
        out_dir = REPO_ROOT / "k8s" / "manifests"
        for fname, content in manifests.items():
            out = out_dir / fname
            changed = write_if_changed(out, content)
            print(f"{'✓ 已更新' if changed else '  无变化'} k8s/manifests/{fname}")

    print(f"\n完成  mode={mode}  "
          f"etcd={cfg['versions']['etcd']}  "
          f"prometheus={cfg['versions']['prometheus']}  "
          f"grafana={cfg['versions']['grafana']}")


if __name__ == "__main__":
    main()
