## 根目录
提示词：
你是一个基础设施和 CICD 领域的智能助手。当前工作目录是项目根目录 `infra_cicd`。请阅读项目结构，了解每个组件部署用途。这个项目是为了首次部署PaaS层基础设施（中间件等）的环境的一键部署工具, 最外层的install.sh主入口。 注意，当前的项目部署都只在一个服务器上，但是保留未来分布式部署的可能。另外尽可能用新版

├── LICENSE  —— 开源证书
├── README.md —— 项目说明
├── claude.md
├── certs —— 域名证书
├── docker —— 如果是 受限区域的服务器，则需要调用docker_proxy.sh走代理，如果非受限地区则不需要
│   ├── docker_proxy.sh
│   └── install.sh
├── etcd —— 部署3.6版本
├── grafana ——  部署 11.5.0
├── install.sh —— 主入口
├── prometheus —— 部署 3.8 版本
├── proxy-srv —— 如果是受限服务器，则需要使用xray代理 + tor，否则只需要 tor
│   ├── apply_torrc.sh
│   ├── install-release.sh
│   ├── offline.sh
│   ├── tor_install.sh
│   └── xray-manager.py
└


用途：
- 生成 README 说明或目录文档
- 规划 CI/CD