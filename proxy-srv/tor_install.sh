#!/usr/bin/env bash

set -euo pipefail

# ============================================================================
# Tor 浏览器和服务安装脚本
# ============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置变量
TOR_VERSION="15.0.14"
TOR_URL="https://dist.torproject.org/torbrowser/${TOR_VERSION}/tor-browser-linux-x86_64-${TOR_VERSION}.tar.xz"
INSTALL_DIR="/opt/tor"
TOR_USER="tor"
TOR_DATA_DIR="/var/lib/tor"
TORRC_PATH="/etc/tor/torrc"
WEBTUNNEL_DIR="/opt/webtunnel/bin"

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# 检查权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        exit 1
    fi
}

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."
    
    local deps=("wget" "tar" "xz" "openssl")
    for cmd in "${deps[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            log_warn "$cmd 未安装"
        fi
    done
}

# 创建用户和目录
setup_environment() {
    log_info "设置环境..."
    
    # 创建 tor 用户（如果不存在）
    if ! id "$TOR_USER" &> /dev/null; then
        log_info "创建用户 $TOR_USER"
        useradd --system --shell /bin/false "$TOR_USER" || true
    fi
    
    # 创建必要的目录
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$TOR_DATA_DIR"
    mkdir -p "$(dirname "$TORRC_PATH")"
}

# 下载 Tor
download_tor() {
    # 参数: 目标临时目录（可选）
    local target_dir=${1:-}
    if [[ -z "$target_dir" ]]; then
        target_dir=$(mktemp -d)
    fi

    log_info "下载 Tor 浏览器 v${TOR_VERSION} 到 ${target_dir}..."

    if ! wget -O "$target_dir/tor-browser.tar.xz" "$TOR_URL"; then
        log_error "下载失败"
        return 1
    fi

    log_info "验证下载完成"
    file "$target_dir/tor-browser.tar.xz"

    echo "$target_dir/tor-browser.tar.xz"
}

# 解压和安装
install_tor() {
    local archive_path="$1"
    
    log_info "解压 Tor..."
    tar -xf "$archive_path" -C "$INSTALL_DIR" --strip-components=1
    
    log_info "设置权限..."
    chown -R "$TOR_USER:$TOR_USER" "$TOR_DATA_DIR"
    chmod 700 "$TOR_DATA_DIR"
    chmod 755 "$INSTALL_DIR"
}

# 配置 torrc
configure_torrc() {
    log_info "配置 torrc..."
    
    cat > "$TORRC_PATH" << 'EOF'
# Tor 配置文件

# SOCKS 端口配置
SocksPort 9050
ControlPort 9051

# 日志配置
Log info syslog

# 数据目录
DataDirectory /var/lib/tor

# 桥接配置 (使用 WebtunnelPT)
UseBridges 1

# WebTunnel 插件配置
ClientTransportPlugin webtunnel exec /opt/webtunnel/bin/webtunnel

# 桥接列表
bridge webtunnel [2001:db8:c0fd:518f:657:3c91:c2ba:a25c]:443 3684CE7D10F45ED6B5257FD86666803E4B08FCB4 url=https://recording.privacy-vbox.de/D7U0yNcEEdK3BDoD22OdeZaX ver=0.0.1
bridge webtunnel [2001:db8:c151:8ea6:7ecb:78eb:97e9:e26a]:443 F6AC833BA7AE92AD01FA99195EA51BBC3265A6E2 url=https://cdn-133.triplebit.dev/6e7f8g9h0i1j2k3l4m5n6o7p ver=0.0.2

# 性能调优（可选）
#MaxCircuitDirtiness 60
#NewCircuitPeriod 30
EOF

    chmod 640 "$TORRC_PATH"
    chown root:"$TOR_USER" "$TORRC_PATH"
    
    log_info "torrc 配置完成"
}

# 创建 systemd 服务
create_systemd_service() {
    log_info "创建 systemd 服务..."
    
    cat > /etc/systemd/system/tor.service << 'EOF'
[Unit]
Description=Tor anonymity network
After=network.target

[Service]
Type=notify
User=tor
Group=tor
ExecStartPre=/usr/bin/test -f /etc/tor/torrc
ExecStart=/opt/tor/tor -f /etc/tor/torrc
ExecReload=/bin/kill -HUP $MAINPID
KillSignal=SIGINT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    log_info "Systemd 服务创建完成"
}

# 启动 Tor 服务
start_tor_service() {
    log_info "启动 Tor 服务..."
    
    systemctl enable tor.service || true
    systemctl start tor.service
    
    sleep 2
    
    if systemctl is-active --quiet tor.service; then
        log_info "Tor 服务已启动"
    else
        log_error "Tor 服务启动失败"
        systemctl status tor.service
        return 1
    fi
}

# 验证安装
verify_installation() {
    log_info "验证安装..."
    
    local socks_port=9050
    local control_port=9051
    
    # 检查端口监听
    if netstat -tuln 2>/dev/null | grep -q ":$socks_port "; then
        log_info "SOCKS 端口 $socks_port 正在监听"
    else
        log_warn "SOCKS 端口 $socks_port 未监听"
    fi
    
    log_info "安装验证完成"
}

# 主函数
main() {
    log_info "开始安装 Tor..."
    
    check_root
    check_dependencies
    setup_environment
    
    # 为下载创建一个持久临时目录，并在脚本退出时清理它
    local temp_dir
    temp_dir=$(mktemp -d)
    trap 'rm -rf "${temp_dir}"' EXIT

    local archive
    archive=$(download_tor "$temp_dir")
    
    install_tor "$archive"
    configure_torrc
    create_systemd_service
    start_tor_service
    verify_installation
    
    log_info "========================================="
    log_info "Tor 安装完成！"
    log_info "========================================="
    log_info "SOCKS 端口: 9050"
    log_info "Control 端口: 9051"
    log_info "数据目录: $TOR_DATA_DIR"
    log_info "配置文件: $TORRC_PATH"
    log_info ""
    log_info "查看日志: journalctl -u tor -f"
    log_info "查看状态: systemctl status tor"
}

# 运行主函数
main "$@"