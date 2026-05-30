
#!/usr/bin/env bash
 
set -euo pipefail
 
# ============================================================================
# Tor + Lyrebird (obfs4/webtunnel PT) 安装脚本
# 适用于 Debian/Ubuntu 系列
# ============================================================================
 
# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
 
# 配置变量
TOR_USER="tor"
TOR_DATA_DIR="/var/lib/tor"
TORRC_PATH="/etc/tor/torrc"
LYREBIRD_INSTALL_PATH="/usr/local/bin/lyrebird"
LYREBIRD_REPO="https://gitlab.torproject.org/tpo/anti-censorship/pluggable-transports/lyrebird"
APPARMOR_PROFILE="/etc/apparmor.d/system_tor"
 
# 上游代理（用于 apt 访问 Tor 仓库，按需修改或留空）
# 留空则不使用代理
UPSTREAM_PROXY="${UPSTREAM_PROXY:-}"
 
# 日志函数
log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${BLUE}====> $*${NC}"; }
 
# ============================================================================
# 工具函数
# ============================================================================
 
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        exit 1
    fi
}
 
# 构建带可选代理的 apt 选项字符串
apt_proxy_opts() {
    if [[ -n "${UPSTREAM_PROXY}" ]]; then
        echo "-o Acquire::http::Proxy=${UPSTREAM_PROXY}"
    fi
}
 
# 检查命令是否存在，不存在则尝试安装
require_cmd() {
    local cmd="$1"
    local pkg="${2:-$1}"
    if ! command -v "$cmd" &>/dev/null; then
        log_warn "${cmd} 未找到，尝试安装 ${pkg}..."
        # shellcheck disable=SC2046
        apt-get install -y $(apt_proxy_opts) "$pkg"
    fi
}
 
# ============================================================================
# Step 1: 安装 Go 并编译 Lyrebird
# ============================================================================
 
install_lyrebird() {
    log_step "安装 Lyrebird (Pluggable Transport)"
 
    # 安装 Go 工具链
    require_cmd go golang
 
    local build_dir
    build_dir=$(mktemp -d)
    trap 'rm -rf "${build_dir:-}"' RETURN
 
    log_info "克隆 Lyrebird 仓库..."
    if ! git clone --depth=1 "$LYREBIRD_REPO" "$build_dir/lyrebird"; then
        log_error "克隆 Lyrebird 失败，请检查网络或仓库地址"
        return 1
    fi
 
    log_info "编译 Lyrebird..."
    (
        cd "$build_dir/lyrebird"
        go build -o lyrebird ./cmd/lyrebird   # 标准入口；如无此路径则回退
    ) || (
        cd "$build_dir/lyrebird"
        go build -o lyrebird .
    )
 
    log_info "安装 Lyrebird 到 ${LYREBIRD_INSTALL_PATH}..."
    install -m 755 "$build_dir/lyrebird/lyrebird" "$LYREBIRD_INSTALL_PATH"
 
    log_info "Lyrebird 安装完成：$(${LYREBIRD_INSTALL_PATH} --version 2>&1 || echo '（版本信息不可用）')"
}
 
# ============================================================================
# Step 2: 从 Tor 官方 Debian 仓库安装 Tor
# ============================================================================
 
add_tor_apt_repo() {
    log_step "添加 Tor 官方 APT 仓库"
 
    require_cmd lsb_release lsb-release
    require_cmd wget wget
    require_cmd gpg gnupg
 
    # 安装 apt-transport-https（旧版 Ubuntu 需要）
    apt-get install -y $(apt_proxy_opts) apt-transport-https
 
    local codename
    codename=$(lsb_release -cs)
    log_info "检测到发行版代号: ${codename}"
 
    local keyring_path="/usr/share/keyrings/tor-archive-keyring.gpg"
    local tor_key_url="https://deb.torproject.org/torproject.org/A3C4F0F979CAA22CDBA8F512EE8CBC9E886DDD89.asc"
 
    log_info "导入 Tor 项目 GPG 公钥..."
    wget -qO- "$tor_key_url" \
        | gpg --dearmor \
        | tee "$keyring_path" >/dev/null
 
    log_info "写入 Tor APT 源..."
    cat > /etc/apt/sources.list.d/tor.list <<EOF
deb     [signed-by=${keyring_path}] https://deb.torproject.org/torproject.org ${codename} main
deb-src [signed-by=${keyring_path}] https://deb.torproject.org/torproject.org ${codename} main
EOF
 
    log_info "更新包列表..."
    # shellcheck disable=SC2046
    apt-get $(apt_proxy_opts) update
}
 
install_tor_package() {
    log_step "安装 Tor"
 
    log_info "安装 tor 和 keyring 包..."
    # shellcheck disable=SC2046
    apt-get install -y $(apt_proxy_opts) tor deb.torproject.org-keyring
 
    log_info "Tor 版本: $(tor --version | head -1)"
}
 
# ============================================================================
# Step 3: 写入 torrc 配置
# ============================================================================
 
configure_torrc() {
    log_step "配置 torrc (${TORRC_PATH})"
 
    # 备份原始配置
    if [[ -f "$TORRC_PATH" ]]; then
        cp "$TORRC_PATH" "${TORRC_PATH}.bak.$(date +%Y%m%d%H%M%S)"
        log_info "原始配置已备份"
    fi
 
    cat > "$TORRC_PATH" <<'EOF'
# ==========================================================
# Tor 配置文件（由安装脚本生成）
# ==========================================================
 
# SOCKS 代理端口（本地应用程序通过此端口访问 Tor 网络）
SocksPort 9050
 
# Control 端口（供 stem/nyx 等工具管理 Tor 进程）
ControlPort 9051
 
# 日志：记录到 syslog，可改为 file 路径便于调试
Log notice syslog
 
# 数据目录
DataDirectory /var/lib/tor
 
# ----------------------------------------------------------
# 桥接 & 混淆传输配置（使用 Lyrebird）
# ----------------------------------------------------------
UseBridges 1
 
# 指定 Lyrebird 作为客户端 PT 插件
# Lyrebird 同时支持 obfs4 和 webtunnel
ClientTransportPlugin obfs4     exec /usr/local/bin/lyrebird
ClientTransportPlugin webtunnel exec /usr/local/bin/lyrebird
 
# 桥接列表（替换为你自己的桥接地址）
# 获取桥接：https://bridges.torproject.org/
# 示例 obfs4 桥接：
# bridge obfs4 <IP>:<PORT> <FINGERPRINT> cert=<CERT> iat-mode=0

bridge webtunnel [2001:db8:43cc:d277:5ba1:dcd1:516e:d983]:443 AD62C15FAC9C8695F41F4BB5D1F16373F906177F url=https://mitch.pmvl.eu/r9mZqSFwOHSQATtQoPWwZQk9 ver=0.0.1
 
# ----------------------------------------------------------
# 可选性能调优
# ----------------------------------------------------------
# MaxCircuitDirtiness 60
# NewCircuitPeriod 30
EOF
 
    chmod 640 "$TORRC_PATH"
    chown root:"$TOR_USER" "$TORRC_PATH"
    log_info "torrc 配置完成"
}
 
# ============================================================================
# Step 4: 修补 AppArmor profile，放行 Lyrebird
# ============================================================================
 
patch_apparmor() {
    log_step "修补 AppArmor Profile"
 
    if ! command -v apparmor_parser &>/dev/null; then
        log_warn "AppArmor 未安装，跳过此步骤"
        return 0
    fi
 
    if [[ ! -f "$APPARMOR_PROFILE" ]]; then
        log_warn "未找到 AppArmor profile: ${APPARMOR_PROFILE}，跳过"
        return 0
    fi
 
    local rule="/usr/local/bin/lyrebird ix,"
 
    # 幂等检查：已存在则不重复添加
    if grep -qF "$rule" "$APPARMOR_PROFILE"; then
        log_info "AppArmor rule 已存在，无需修改"
        return 0
    fi
 
    log_info "在 AppArmor profile 中添加 Lyrebird 规则..."
    # 在最后一个 } 之前插入规则
    sed -i "s|^}$|  ${rule}\n}|" "$APPARMOR_PROFILE"
 
    log_info "重载 AppArmor..."
    systemctl restart apparmor
 
    log_info "AppArmor 修补完成"
}
 
# ============================================================================
# Step 5: 启动并验证 Tor 服务
# ============================================================================
 
start_and_verify() {
    log_step "启动 Tor 服务"
 
    systemctl enable tor@default
    systemctl restart tor@default
 
    log_info "等待 Tor 建立回路（最长 60 秒）..."
    local waited=0
    until journalctl -u tor@default --no-pager -n 20 2>/dev/null \
          | grep -qE "Bootstrapped 100%|Done"; do
        sleep 5
        waited=$((waited + 5))
        if [[ $waited -ge 60 ]]; then
            log_warn "等待超时，Tor 可能仍在连接桥接，请稍后手动检查"
            break
        fi
        log_info "  已等待 ${waited}s..."
    done
 
    log_step "验证：通过 SOCKS5 检测出口 IP"
    if command -v curl &>/dev/null; then
        local result
        if result=$(curl --silent --max-time 15 \
                         --socks5 127.0.0.1:9050 \
                         http://ip-api.com/json); then
            log_info "出口 IP 信息:"
            echo "$result" | python3 -m json.tool 2>/dev/null || echo "$result"
        else
            log_warn "curl 测试失败（Tor 可能尚未完全就绪，请稍后重试）"
            log_warn "手动测试命令："
            log_warn "  curl --socks5 127.0.0.1:9050 http://ip-api.com/json"
        fi
    else
        log_warn "curl 未安装，跳过 IP 验证"
        log_warn "手动测试命令："
        log_warn "  curl --socks5 127.0.0.1:9050 http://ip-api.com/json"
    fi
}
 
# ============================================================================
# 主流程
# ============================================================================
 
main() {
    log_info "================================================"
    log_info " Tor + Lyrebird 安装脚本"
    log_info "================================================"
 
    check_root
 
    # 可通过环境变量传入上游代理，例如：
    #   UPSTREAM_PROXY=http://127.0.0.1:10808 ./install_tor.sh
    if [[ -n "${UPSTREAM_PROXY}" ]]; then
        log_info "使用上游代理: ${UPSTREAM_PROXY}"
    fi
 
    install_lyrebird
    add_tor_apt_repo
    install_tor_package
    configure_torrc
    patch_apparmor
    start_and_verify
 
    log_info ""
    log_info "================================================"
    log_info " 安装完成！"
    log_info "================================================"
    log_info "SOCKS 端口     : 127.0.0.1:9050"
    log_info "Control 端口   : 127.0.0.1:9051"
    log_info "数据目录       : ${TOR_DATA_DIR}"
    log_info "配置文件       : ${TORRC_PATH}"
    log_info "Lyrebird       : ${LYREBIRD_INSTALL_PATH}"
    log_info ""
    log_info "常用命令："
    log_info "  查看日志     : journalctl -u tor@default -f"
    log_info "  查看状态     : systemctl status tor@default"
    log_info "  测试出口 IP  : curl --socks5 127.0.0.1:9050 http://ip-api.com/json"
    log_info "================================================"
}
 
main "$@"