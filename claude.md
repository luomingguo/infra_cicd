# infra_cicd — 项目上下文

## 项目定位

PaaS 层基础设施（中间件等）的首次部署工具。
支持单机（docker compose）和分布式（k8s/k3s/kind）两种模式，通过 `config.yaml` 切换。
支持受限区域（墙内，xray + tor）与非受限区域（仅 tor）自动判断。

---

## 目录结构

```
infra_cicd/
├── config.yaml                  # ★ 唯一人工编辑的配置文件
├── config.mk                    # 自动生成（config-gen.py 产物，.gitignore）
├── runtime.mk                   # 自动生成（每次 make 时写入网络环境，.gitignore）
├── Makefile                     # 根编排层：纯循环，不感知任何具体模块
├── common.mk                    # 工具层：颜色、日志宏、require_root、CURL、APT
├── .gitignore
│
├── scripts/
│   ├── config-gen.py            # config.yaml → config.mk + docker-compose.yml + k8s manifests
│   ├── xray-manager.py          # xray 订阅管理 + 自动测速切换 + systemd watchdog
│   ├── xray-install.sh          # xray-core 安装（来自 XTLS/Xray-install）
│   └── tor-install.sh           # tor + lyrebird 安装
│
├── proxy-srv/                   # 代理层（裸机安装，两种部署模式共用）
│   └── Makefile
│
├── docker/
│   ├── Makefile                 # Docker Engine 安装 + daemon 代理配置
│   └── compose/
│       ├── Makefile             # compose 生命周期（up/down/status/test/logs）
│       └── docker-compose.yml   # ★ 自动生成，勿手动编辑
│
├── k8s/
│   ├── Makefile                 # k8s 生命周期（兼容 k3s / kind / vanilla）
│   ├── manifests/               # ★ 自动生成，勿手动编辑
│   └── kind-config.yaml
│
├── etcd/Makefile
├── prometheus/Makefile
├── grafana/Makefile
│
├── certs/                       # 域名证书（手动放置，.gitignore）
└── deploy.yml                   # CI：config-check → lint → deploy → health-check
```

---

## 核心架构原则

### 1. 单一配置源

**只编辑 `config.yaml`**，其余配置文件均为派生产物：

```
config.yaml
    └─► scripts/config-gen.py
            ├── config.mk                          （所有 Makefile include）
            ├── docker/compose/docker-compose.yml  （compose 模式）
            └── k8s/manifests/*.yaml               （k8s 模式）
```

### 2. Makefile 分层

```
根 Makefile        纯编排，不知道有哪些模块，只做循环
    ├── common.mk  工具层：颜色变量、日志宏、require_root、CURL、APT（唯一定义处）
    └── */Makefile 各模块自治，include common.mk 获取所有工具
```

**子模块 include（固定写法，一行）：**
```makefile
include $(or $(INFRA_COMMON_MK), ../common.mk)
```
- 通过根 Makefile 调用时：`INFRA_COMMON_MK` 由根 export 为绝对路径
- 直接调用时（`make -C proxy-srv install`）：回退相对路径 `../common.mk`
- `common.mk` 自动加载 `config.mk` 和 `runtime.mk`，子模块无需关心

**子模块契约**（每个含 Makefile 的目录必须实现）：

| target | 用途 |
|--------|------|
| `install` | 幂等安装 |
| `uninstall` | 卸载（保留数据） |
| `status` | 查看运行状态 |
| `test` | 健康检查（exit 0 = pass） |

### 3. 模块注册机制

根 Makefile **不感知任何具体模块**，列表和顺序全部来自 `config.yaml`：

```yaml
deploy:
  modules:
    - module: proxy-srv
    - module: docker/compose
      only_mode: compose
    - module: k8s
      only_mode: k8s
```

`config-gen.py` 按 `mode` 过滤后写入 `config.mk`：
```makefile
DEPLOY_MODULES   := proxy-srv docker/compose etcd prometheus grafana
DEPLOY_SUMMARIES := grafana|http://host:3000
```

**新增模块只需：**
1. 新建目录 + 实现四个 target
2. `config.yaml` 的 `deploy.modules` 追加一行
3. `make config-gen`
4. 根 Makefile **零修改**

### 4. 权限控制

不做全局 root 检查。只在真正需要的 recipe 第一行内联调用：
```makefile
$(call require_root)   # 定义在 common.mk
```
需要 root：`apt-get install`、`useradd`、写 `/usr/local/bin/`、`/etc/`、`systemctl enable/start`。
**不需要 root**：`docker compose`、`kubectl`、`make test`、`make status`、`make config-gen`。

### 5. 代理层幂等性

`proxy-srv/Makefile` 在 make **解析阶段**检测当前状态，已运行则直接跳过：
```makefile
XRAY_READY := $(shell command -v xray &>/dev/null \
  && systemctl is-active --quiet xray 2>/dev/null && echo true || echo false)
TOR_READY  := $(shell systemctl is-active --quiet tor@default 2>/dev/null \
  && nc -z 127.0.0.1 $(TOR_SOCKS_PORT) 2>/dev/null && echo true || echo false)
```

### 6. 部署模式

| 模式 | 场景 | 入口模块 |
|------|------|---------|
| `compose` | 单机，资源有限 | `docker/compose` |
| `k8s` | 分布式，k3s/kind/vanilla | `k8s` |

切换：修改 `config.yaml` 的 `deploy.mode` → `make config-gen` → `make install`。

### 7. 网络环境

| 值 | 行为 |
|----|------|
| `auto` | 自动检测（访问 google.com，超时判定为受限） |
| `restricted` | 强制受限：xray-core + tor，xray HTTP 代理作为 tor 上游 |
| `open` | 强制直连：仅 tor |

检测结果写入 `runtime.mk`，子模块通过 `common.mk` 读取 `PROXY_HTTP` / `PROXY_SOCKS5`，
`$(CURL)` 和 `$(APT)` 自动携带代理参数。

### 8. scripts/ 目录

| 文件 | 说明 | 调用方 |
|------|------|--------|
| `config-gen.py` | 配置生成，**勿手动执行**，走 `make config-gen` | 根 Makefile |
| `xray-manager.py` | xray 订阅管理，由 proxy-srv/Makefile 调用 | proxy-srv/Makefile |
| `xray-install.sh` | xray-core 安装（XTLS 官方脚本），由 proxy-srv/Makefile 调用 | proxy-srv/Makefile |
| `tor-install.sh` | tor + lyrebird 安装，由 proxy-srv/Makefile 调用 | proxy-srv/Makefile |

---

## 常用命令

```bash
# 首次初始化
make config-gen

# 改了 config.yaml 后预览变更
make config-diff

# 查看当前生效的模块列表和网络环境
make config-show

# 全量部署
sudo make install

# 健康检查
make test

# 查看状态
make status

# 清理所有生成文件（可重新 config-gen 恢复）
make clean

# 直接调试某个子模块（无需通过根）
make -C proxy-srv test
make -C docker/compose logs
make -C k8s port-forward

# xray 订阅管理
make -C proxy-srv xray-update
make -C proxy-srv xray-status
```

---

## 版本与端口（均在 config.yaml 管理）

| 服务 | 当前版本 | 默认端口 |
|------|----------|---------|
| etcd | 3.6.0 | 2379（client）/ 2380（peer） |
| Prometheus | 3.8.0 | 9090 |
| node_exporter | 1.8.2 | 9100 |
| Grafana | 11.5.0 | 3000 |
| xray socks5 | latest | 10808 |
| xray http | latest | 10809 |
| tor socks5 | latest | 9050 |

---

## 敏感配置处理

不入 `config.yaml`，通过环境变量或 GitHub Secrets 注入：

| 变量 | 用途 |
|------|------|
| `XRAY_SUB_URL` | xray 订阅地址 |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin 密码 |

---

## AI 助手工作指引

- **修改版本/端口/域名**：只改 `config.yaml`，然后 `make config-gen`
- **新增服务**：新建目录 + Makefile（实现四个 target）+ `config.yaml` 的 `deploy.modules` 追加一行
- **颜色变量/日志宏/require_root/CURL/APT**：统一在 `common.mk` 定义，子模块不要重复定义
- **root 检查**：用 `$(call require_root)` 内联在需要的 recipe 第一行，不要加 `_check-root` 前置依赖
- **派生文件**：`config.mk`、`runtime.mk`、`docker-compose.yml`、`k8s/manifests/` 均为生成物，不要直接编辑
- **根 Makefile**：不得 hardcode 任何模块名，所有模块感知通过 `$(DEPLOY_MODULES)` 循环完成
- **脚本**：复杂安装逻辑放 `scripts/`，简单配置写操作内联进对应模块 Makefile
- **调试**：`make config-show` 确认配置 → `make -C <module> test` 定位问题
