# infra_cicd — 项目上下文

## 项目定位

PaaS 层基础设施（中间件等）的一键部署工具。
当前单机部署，保留分布式扩展能力。支持受限区域（墙内）与非受限区域自动判断。

---

## 目录结构

```
infra_cicd/
├── config.yaml                  # ★ 唯一人工编辑的配置文件（版本、端口、域名、模式等）
├── config.mk                    # 自动生成，勿手动编辑（由 config-gen.py 从 config.yaml 生成）
├── Makefile                     # 根编排层，按 deploy.mode 路由到 compose 或 k8s
├── common.mk                    # 子模块共用工具函数（日志、代理、架构检测、systemd 操作）
│
├── scripts/
│   └── config-gen.py            # config.yaml → config.mk + docker-compose.yml + k8s manifests
│
├── proxy-srv/                   # 代理层（裸机安装，两种部署模式都需要）
│   ├── Makefile
│   ├── install-release.sh       # xray-core 安装（XTLS 官方脚本）
│   ├── xray-manager.py          # xray 订阅管理 + 自动测速切换 + systemd watchdog
│   ├── tor_install.sh           # tor + lyrebird (webtunnel/obfs4) 安装
│   ├── apply_torrc.sh           # 更新 torrc（受限区域：配置 xray 作为 tor 上游代理）
│   └── offline.sh               # 离线安装辅助
│
├── docker/
│   ├── compose/
│   │   ├── Makefile             # compose 生命周期（up/down/status/test/logs）
│   │   └── docker-compose.yml   # ★ 自动生成，勿手动编辑
│   ├── install.sh               # Docker Engine 安装
│   └── docker_proxy.sh          # Docker daemon 代理配置（受限区域使用）
│
├── k8s/
│   ├── Makefile                 # k8s 生命周期（兼容 k3s / kind / vanilla）
│   ├── manifests/               # ★ 自动生成，勿手动编辑
│   │   ├── 00-namespace.yaml
│   │   ├── 10-etcd.yaml         # StatefulSet + headless svc + client svc
│   │   ├── 20-prometheus.yaml   # Deployment + svc + PVC
│   │   ├── 30-grafana.yaml      # Deployment + svc + PVC
│   │   └── kustomization.yaml
│   └── kind-config.yaml         # kind 本地集群配置
│
├── templates/
│   ├── compose/
│   │   ├── prometheus.yml       # Prometheus 抓取配置模板
│   │   ├── prometheus-rules/    # 告警规则
│   │   └── grafana-provisioning/ # 数据源 + Dashboard provisioning
│   └── k8s/
│       └── prometheus-configmap.yaml
│
├── certs/                       # 域名证书（手动放置）
│   ├── fullchain.pem
│   └── privkey.pem
│
└── .github/
    └── workflows/
        └── deploy.yml           # CI：config-check → lint → deploy → health-check
```

---

## 核心架构原则

### 1. 单一配置源

**只编辑 `config.yaml`**，其他配置文件均为派生产物：

```
config.yaml
    └─► config-gen.py
            ├── config.mk              （被所有 Makefile include）
            ├── docker/compose/docker-compose.yml
            └── k8s/manifests/*.yaml
```

### 2. Makefile 分层

```
根 Makefile           编排层，不含安装逻辑，按 DEPLOY_MODE 路由
    ├── common.mk     工具函数层（日志/代理/systemd），无配置
    ├── proxy-srv/Makefile   裸机层，两种模式共用
    ├── docker/compose/Makefile   compose 模式
    └── k8s/Makefile              k8s 模式
```

**子模块契约**：每个含 Makefile 的目录必须实现：

- `install` — 幂等安装
- `uninstall` — 卸载（保留数据）
- `status` — 查看运行状态
- `test` — 健康检查（exit 0 = pass）

**添加新模块**：新建目录 + 实现上述 target，在 `config.yaml` 的 `deploy.order` 追加，运行 `make config-gen`，根 Makefile 无需修改。

### 3. 部署模式

| 模式      | 场景                     | 入口                      |
| --------- | ------------------------ | ------------------------- |
| `compose` | 单机，资源有限           | `docker/compose/Makefile` |
| `k8s`     | 分布式，k3s/kind/vanilla | `k8s/Makefile`            |

切换方式：修改 `config.yaml` 中 `deploy.mode`，运行 `make config-gen && make install`。

### 4. 网络环境

| 值           | 行为                                                   |
| ------------ | ------------------------------------------------------ |
| `auto`       | 自动检测（访问 google.com，超时判定为受限）            |
| `restricted` | 强制受限：安装 xray-core + tor，xray 作为 tor 上游代理 |
| `open`       | 强制直连：仅安装 tor                                   |

proxy-srv 是裸机组件，两种部署模式都需要，优先于 infra 安装。

---

## 常用命令

```bash
# 首次初始化
make config-gen

# 查看当前配置
make config-show

# 改了 config.yaml 后预览变更
make config-diff

# 全量部署
sudo make install

# 只部署指定模块
sudo make install MODULES="proxy-srv"

# 健康检查
sudo make test

# 查看状态
make status

# compose 模式：查看日志
make -C docker/compose logs

# k8s 模式：本地端口转发（调试）
make -C k8s port-forward

# 迁移检查（compose → k8s）
make migrate-compose-to-k8s

# 数据备份
make backup
```

---

## 版本与端口（均在 config.yaml 管理）

| 服务          | 当前版本 | 默认端口                     |
| ------------- | -------- | ---------------------------- |
| etcd          | 3.6.0    | 2379（client）/ 2380（peer） |
| Prometheus    | 3.8.0    | 9090                         |
| node_exporter | 1.8.2    | 9100                         |
| Grafana       | 11.5.0   | 3000                         |
| xray socks5   | latest   | 10808                        |
| tor socks5    | latest   | 9050                         |

---

## 敏感配置处理

不入 `config.yaml`，通过 GitHub Secrets 在 CI 中动态注入：

| Secret                   | 对应配置               |
| ------------------------ | ---------------------- |
| `XRAY_SUB_URL`           | proxy.xray.sub_url     |
| `GRAFANA_ADMIN_PASSWORD` | grafana.admin_password |

---

## etcd 扩展为集群

在 `config.yaml` 中追加节点，无需修改任何 Makefile：

```yaml
etcd:
  nodes:
    - { name: etcd-0, ip: 10.0.0.1 }
    - { name: etcd-1, ip: 10.0.0.2 }
    - { name: etcd-2, ip: 10.0.0.3 }
```

`config-gen.py` 自动计算 `initial-cluster` 字符串，compose 生成多个 service，k8s 更新 StatefulSet replicas。

---

## AI 助手工作指引

- **修改版本**：只改 `config.yaml` 的 `versions` 字段，不改 Makefile
- **新增服务**：新建目录 + Makefile（实现四个 target）+ 在 `config.yaml` 注册
- **修改端口**：只改 `config.yaml`，同步更新 `firewall.allow_ports`
- **生成配置**：修改 `config.yaml` 后必须运行 `make config-gen`，`config.mk` / `docker-compose.yml` / `k8s/manifests/` 均为派生文件，不直接编辑
- **调试优先级**：先 `make config-show` 确认配置，再 `make test` 定位问题