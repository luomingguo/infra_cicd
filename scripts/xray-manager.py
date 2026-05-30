#!/usr/bin/env python3
"""
xray-manager —— xray-core 订阅管理器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法:
  xray-manager update [订阅URL]   拉取订阅，测速，应用最快节点（优先 hy2）
  xray-manager check              健康检查，故障时自动切换到下一节点
  xray-manager switch [N]         切换到第 N 个节点（默认下一个）
  xray-manager list               显示所有节点排名及延迟
  xray-manager status             显示当前节点与健康状态
  xray-manager install            安装 systemd 健康检查定时器（每 60 秒）
 
文件布局:
  /usr/local/etc/xray/
  ├── config.json          ← xray 实际读取的配置（由本脚本维护）
  ├── nodes/               ← 所有节点配置（每次 update 覆盖）
  │   ├── 001_xxx.json
  │   └── ...
  └── .state.json          ← 状态：订阅地址、排名列表、当前索引
"""
 
import sys, os, json, base64, re, time, shutil, socket
import urllib.parse, urllib.request, subprocess, threading
from copy import deepcopy
from datetime import datetime
 
# ─────────────────────────────────────────────────────────────────────────────
#  路径常量
# ─────────────────────────────────────────────────────────────────────────────
XRAY_DIR   = "/usr/local/etc/xray"
NODES_DIR  = os.path.join(XRAY_DIR, "nodes")
CONFIG     = os.path.join(XRAY_DIR, "config.json")   # xray -c config.json 读这里
STATE_FILE = os.path.join(XRAY_DIR, ".state.json")
XRAY_SVC   = "xray"                                   # systemctl 服务名
 
# 健康检查：通过本地 socks 代理访问此 URL，HTTP 204 表示正常
HEALTH_URL      = "https://www.gstatic.com/generate_204"
SOCKS_PORT      = 10808
HEALTH_TIMEOUT  = 10          # 秒
MAX_FAIL_COUNT  = 3           # 连续失败多少次才切换
PING_COUNT      = 3           # 测速 ping 次数
PING_TIMEOUT    = 2           # 每次 ping 超时（秒）
 
# ─────────────────────────────────────────────────────────────────────────────
#  公共 DNS / 路由常量（与原 gen_xray_config.py 一致）
# ─────────────────────────────────────────────────────────────────────────────
DNS_HOSTS = {
    "dns.google":                       ["8.8.8.8","8.8.4.4","2001:4860:4860::8888","2001:4860:4860::8844"],
    "dns.alidns.com":                   ["223.5.5.5","223.6.6.6","2400:3200::1","2400:3200:baba::1"],
    "one.one.one.one":                  ["1.1.1.1","1.0.0.1","2606:4700:4700::1111","2606:4700:4700::1001"],
    "1dot1dot1dot1.cloudflare-dns.com": ["1.1.1.1","1.0.0.1","2606:4700:4700::1111","2606:4700:4700::1001"],
    "cloudflare-dns.com":               ["104.16.249.249","104.16.248.249","2606:4700::6810:f8f9","2606:4700::6810:f9f9"],
    "dns.cloudflare.com":               ["104.16.132.229","104.16.133.229","2606:4700::6810:84e5","2606:4700::6810:85e5"],
    "dot.pub":                          ["1.12.12.12","120.53.53.53"],
    "doh.pub":                          ["1.12.12.12","120.53.53.53"],
    "dns.quad9.net":                    ["9.9.9.9","149.112.112.112","2620:fe::fe","2620:fe::9"],
    "dns.yandex.net":                   ["77.88.8.8","77.88.8.1","2a02:6b8::feed:0ff","2a02:6b8:0:1::feed:0ff"],
    "dns.sb":                           ["185.222.222.222","2a09::"],
    "dns.umbrella.com":                 ["208.67.220.220","208.67.222.222","2620:119:35::35","2620:119:53::53"],
    "dns.sse.cisco.com":                ["208.67.220.220","208.67.222.222","2620:119:35::35","2620:119:53::53"],
    "engage.cloudflareclient.com":      ["162.159.192.1"],
}
DIRECT_DNS_IPS = [
    "223.5.5.5","223.6.6.6","2400:3200::1","2400:3200:baba::1",
    "119.29.29.29","1.12.12.12","120.53.53.53",
    "2402:4e00::","2402:4e00:1::","180.76.76.76","2400:da00::6666",
    "114.114.114.114","114.114.115.115","114.114.114.119","114.114.115.119",
    "114.114.114.110","114.114.115.110","180.184.1.1","180.184.2.2",
    "101.226.4.6","218.30.118.6","123.125.81.6","140.207.198.6",
    "1.2.4.8","210.2.4.8","52.80.66.66","117.50.22.22",
    "2400:7fc0:849e:200::4","2404:c2c0:85d8:901::4",
    "117.50.10.10","52.80.52.52","2400:7fc0:849e:200::8","2404:c2c0:85d8:901::8",
    "117.50.60.30","52.80.60.30",
]
DNS_PROC = [
    "v2ray","mihomo-darwin-amd64-v1","mihomo-darwin-amd64","mihomo-darwin-arm64",
    "clash","mihomo","hysteria","naive","naiveproxy","tuic-client","tuic",
    "sing-box-client","sing-box","juicity-client","juicity",
    "hysteria-windows-amd64","hysteria-linux-amd64",
    "brook_windows_amd64","brook_linux_amd64","brook",
    "overtls-bin","overtls","shadowquic","mieru",
]
DIRECT_PROC = DNS_PROC + ["xray","xray/","self/"]
 
# ─────────────────────────────────────────────────────────────────────────────
#  xray 配置生成
# ─────────────────────────────────────────────────────────────────────────────
 
def build_config(idx: int, outbound: dict, server_host: str) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "dns": {
            "hosts": DNS_HOSTS,
            "servers": [
                {"address":"119.29.29.29",
                 "domains":["domain:alidns.com","domain:doh.pub","domain:dot.pub",
                            "domain:360.cn","domain:onedns.net", server_host],
                 "skipFallback":True, "tag":"direct-dns-1"},
                {"address":"https://cloudflare-dns.com/dns-query",
                 "domains":["geosite:google"], "skipFallback":True},
                {"address":"119.29.29.29",
                 "domains":["geosite:private","geosite:cn"],
                 "skipFallback":True, "tag":"direct-dns-2"},
                {"address":"119.29.29.29",
                 "domains":["full:cloudflare-dns.com"], "skipFallback":True},
                "https://cloudflare-dns.com/dns-query",
            ],
            "tag": "dns-module",
        },
        "inbounds": [
            {"tag":"socks","port":SOCKS_PORT,"listen":"127.0.0.1","protocol":"mixed",
             "sniffing":{"enabled":True,"destOverride":["http","tls"],"routeOnly":False},
             "settings":{"auth":"noauth","udp":True,"allowTransparent":False}},
            {"tag":"tun","protocol":"tun",
             "sniffing":{"enabled":True,"destOverride":["http","tls"],"routeOnly":False},
             "settings":{"name":f"tun{idx}","MTU":9000,"gateway":["172.18.0.1/30"],
                         "autoSystemRoutingTable":["0.0.0.0/0","::/0"],
                         "autoOutboundsInterface":"auto"}},
        ],
        "outbounds": [
            outbound,
            {"tag":"direct","protocol":"freedom"},
            {"tag":"block","protocol":"blackhole"},
            {"tag":"dns","protocol":"dns"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type":"field","inboundTag":["api"],"outboundTag":"api"},
                {"port":"135,137-139,5353","network":"udp","outboundTag":"block"},
                {"outboundTag":"block","ip":["224.0.0.0/3","ff00::/8"]},
                {"port":"53","outboundTag":"dns","process":DNS_PROC},
                {"outboundTag":"direct","process":DIRECT_PROC},
                {"port":"53","inboundTag":["tun"],"outboundTag":"dns"},
                {"type":"field","port":"443","network":"udp","outboundTag":"block"},
                {"type":"field","outboundTag":"proxy","domain":["geosite:google"]},
                {"type":"field","outboundTag":"direct","ip":["geoip:private"]},
                {"type":"field","outboundTag":"direct","domain":["geosite:private"]},
                {"type":"field","outboundTag":"direct","ip":DIRECT_DNS_IPS},
                {"type":"field","outboundTag":"direct",
                 "domain":["domain:alidns.com","domain:doh.pub","domain:dot.pub",
                           "domain:360.cn","domain:onedns.net"]},
                {"type":"field","outboundTag":"direct","ip":["geoip:cn"]},
                {"type":"field","outboundTag":"direct","domain":["geosite:cn"]},
                {"type":"field","inboundTag":["direct-dns-1","direct-dns-2"],"outboundTag":"direct"},
                {"type":"field","inboundTag":["dns-module"],"outboundTag":"proxy"},
            ],
        },
    }
 
# ─────────────────────────────────────────────────────────────────────────────
#  协议解析器（vless / vmess / trojan / hysteria2 / hysteria / ss）
# ─────────────────────────────────────────────────────────────────────────────
 
def _stream(params, host):
    raw_type = params.get("type","tcp")
    security = params.get("security","none")
    net = "raw" if raw_type in ("tcp","raw") else raw_type
    s = {"network": net, "security": security}
    if security == "tls":
        s["tlsSettings"] = {"allowInsecure": params.get("insecure","0")=="1",
                             "serverName": params.get("sni", host),
                             "fingerprint": params.get("fp","chrome")}
    elif security == "reality":
        s["realitySettings"] = {"serverName": params.get("sni",""),
                                 "fingerprint": params.get("fp","chrome"),
                                 "show": False,
                                 "publicKey": params.get("pbk",""),
                                 "shortId": params.get("sid",""),
                                 "spiderX": params.get("spx","/"),
                                 "mldsa65Verify": ""}
    if raw_type == "ws":
        s["wsSettings"] = {"path": urllib.parse.unquote(params.get("path","/")),
                           "host": params.get("host", host)}
    elif raw_type == "grpc":
        s["grpcSettings"] = {"serviceName": params.get("serviceName",""), "multiMode": False}
    elif raw_type in ("h2","http"):
        s["httpSettings"] = {"path": urllib.parse.unquote(params.get("path","/")),
                             "host": [params.get("host", host)]}
    elif raw_type == "httpupgrade":
        s["httpupgradeSettings"] = {"path": urllib.parse.unquote(params.get("path","/")),
                                    "host": params.get("host", host)}
    return s
 
def parse_vless(uri):
    try:
        p = urllib.parse.urlparse(uri)
        params = dict(urllib.parse.parse_qsl(p.query))
        user = {"id": p.username, "email":"t@t.tt", "security":"auto", "encryption":"none"}
        if params.get("flow"): user["flow"] = params["flow"]
        ob = {"tag":"proxy","protocol":"vless",
              "settings":{"vnext":[{"address":p.hostname,"port":p.port,"users":[user]}]},
              "streamSettings": _stream(params, p.hostname),
              "mux":{"enabled":False,"concurrency":-1}}
        return ob, p.hostname, urllib.parse.unquote(p.fragment or p.hostname)
    except: return None,None,None
 
def parse_vmess(uri):
    try:
        b64 = uri[8:] + "=="
        d = json.loads(base64.b64decode(b64).decode())
        host = d.get("add",""); port = int(d.get("port",443))
        net = d.get("net","tcp"); tls_v = d.get("tls","")
        net_x = "raw" if net in ("tcp","raw") else net
        s = {"network": net_x, "security": tls_v or "none"}
        if tls_v == "tls":
            s["tlsSettings"] = {"allowInsecure":False,
                                 "serverName": d.get("sni","") or d.get("host",host),
                                 "fingerprint": d.get("fp","chrome")}
        if net == "ws":
            s["wsSettings"] = {"path": d.get("path","/"), "host": d.get("host",host)}
        elif net == "grpc":
            s["grpcSettings"] = {"serviceName": d.get("path",""), "multiMode":False}
        ob = {"tag":"proxy","protocol":"vmess",
              "settings":{"vnext":[{"address":host,"port":port,
                          "users":[{"id":d.get("id",""),"alterId":int(d.get("aid",0)),
                                    "email":"t@t.tt","security":"auto"}]}]},
              "streamSettings":s,"mux":{"enabled":False,"concurrency":-1}}
        return ob, host, d.get("ps", host)
    except: return None,None,None
 
def parse_trojan(uri):
    try:
        p = urllib.parse.urlparse(uri)
        params = dict(urllib.parse.parse_qsl(p.query))
        ob = {"tag":"proxy","protocol":"trojan",
              "settings":{"servers":[{"address":p.hostname,"port":p.port,
                                       "password":p.username,"email":"t@t.tt"}]},
              "streamSettings": _stream(params, p.hostname),
              "mux":{"enabled":False,"concurrency":-1}}
        return ob, p.hostname, urllib.parse.unquote(p.fragment or p.hostname)
    except: return None,None,None
 
def parse_hysteria2(uri):
    try:
        if uri.startswith("hy2://"): uri = "hysteria2://" + uri[6:]
        p = urllib.parse.urlparse(uri)
        params = dict(urllib.parse.parse_qsl(p.query))
        ob = {"tag":"proxy","protocol":"hysteria",
              "settings":{"address":p.hostname,"port":p.port,"version":2},
              "streamSettings":{
                  "network":"hysteria","security":"tls",
                  "tlsSettings":{"allowInsecure": params.get("insecure","0")=="1",
                                  "serverName": params.get("sni", p.hostname)},
                  "hysteriaSettings":{"version":2,"auth":p.username},
                  "finalmask":{"quicParams":{"congestion":"brutal",
                                             "brutalUp":"100mbps","brutalDown":"100mbps"}},
              },
              "mux":{"enabled":False}}
        return ob, p.hostname, urllib.parse.unquote(p.fragment or p.hostname)
    except: return None,None,None
 
def parse_hysteria1(uri):
    try:
        p = urllib.parse.urlparse(uri)
        params = dict(urllib.parse.parse_qsl(p.query))
        sni = params.get("peer", p.hostname) or params.get("sni", p.hostname)
        ob = {"tag":"proxy","protocol":"hysteria",
              "settings":{"address":p.hostname,"port":p.port,"version":1},
              "streamSettings":{
                  "network":"hysteria","security":"tls",
                  "tlsSettings":{"allowInsecure": params.get("insecure","0")=="1",
                                  "serverName": sni},
                  "hysteriaSettings":{"version":1,"auth":params.get("auth","")},
                  "finalmask":{"quicParams":{"congestion":"brutal",
                                             "brutalUp":"100mbps","brutalDown":"100mbps"}},
              },
              "mux":{"enabled":False}}
        return ob, p.hostname, urllib.parse.unquote(p.fragment or p.hostname)
    except: return None,None,None
 
def parse_ss(uri):
    try:
        name = ""
        if "#" in uri: uri, frag = uri.rsplit("#",1); name = urllib.parse.unquote(frag)
        body = uri[5:]
        if "@" in body:
            ui, hi = body.rsplit("@",1)
            try: dec = base64.b64decode(ui+"==").decode(); method,pw = dec.split(":",1)
            except: method,pw = ui.split(":",1)
        else:
            dec = base64.b64decode(body+"==").decode()
            mp,hi = dec.rsplit("@",1); method,pw = mp.split(":",1)
        host,port_s = hi.rsplit(":",1)
        ob = {"tag":"proxy","protocol":"shadowsocks",
              "settings":{"servers":[{"address":host,"port":int(port_s),
                                       "method":method,"password":pw,"email":"t@t.tt"}]},
              "streamSettings":{"network":"raw"},"mux":{"enabled":False,"concurrency":-1}}
        return ob, host, name or host
    except: return None,None,None
 
PARSERS = [
    ("vless://",     parse_vless),
    ("vmess://",     parse_vmess),
    ("trojan://",    parse_trojan),
    ("hysteria2://", parse_hysteria2),
    ("hy2://",       parse_hysteria2),
    ("hysteria://",  parse_hysteria1),
    ("ss://",        parse_ss),
]
 
def parse_node(line):
    for prefix, fn in PARSERS:
        if line.startswith(prefix): return fn(line)
    return None,None,None
 
def is_hy2(outbound):
    """判断是否为 hysteria2 节点。"""
    if outbound.get("protocol") != "hysteria": return False
    return outbound.get("settings",{}).get("version",0) == 2
 
# ─────────────────────────────────────────────────────────────────────────────
#  订阅拉取
# ─────────────────────────────────────────────────────────────────────────────
 
def fetch_sub(url):
    req = urllib.request.Request(url, headers={"User-Agent":"v2rayN/6.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8","replace").strip()
    try:
        padded = raw + "=" * (-len(raw) % 4)
        dec = base64.b64decode(padded).decode("utf-8","replace")
        if any(dec.lstrip().startswith(p) for p,_ in PARSERS) or \
           any(("\n"+p) in dec for p,_ in PARSERS):
            return dec
    except: pass
    return raw
 
# ─────────────────────────────────────────────────────────────────────────────
#  延迟测量（ping）
# ─────────────────────────────────────────────────────────────────────────────
 
def measure_latency(host: str) -> float:
    """
    用 ping 测量主机平均 RTT（毫秒）。
    失败或超时返回 9999.0。
    hy2 是 UDP/QUIC，TCP connect 无意义，ping 是最合理的轻量测速手段。
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT), host],
            capture_output=True, text=True, timeout=PING_COUNT * PING_TIMEOUT + 3
        )
        for line in result.stdout.splitlines():
            # Linux: rtt min/avg/max/mdev = 12.3/15.6/20.1/3.2 ms
            m = re.search(r"(\d+\.?\d+)/(\d+\.?\d+)/(\d+\.?\d+)", line)
            if m:
                return float(m.group(2))   # avg
    except Exception:
        pass
    return 9999.0
 
def measure_all(nodes: list) -> list:
    """
    并发测速，返回带 latency_ms 字段的节点列表。
    nodes: [{"file":..., "proto":..., "name":..., "host":...}, ...]
    """
    results = [None] * len(nodes)
    def worker(i, node):
        ms = measure_latency(node["host"])
        results[i] = {**node, "latency_ms": ms}
        status = f"{ms:.0f} ms" if ms < 9999 else "超时"
        print(f"    {'[hy2]' if node['proto']=='hysteria2' else '[' + node['proto'] + ']'}"
              f" {node['name'][:40]}  {status}")
 
    threads = [threading.Thread(target=worker, args=(i,n)) for i,n in enumerate(nodes)]
    for t in threads: t.start()
    for t in threads: t.join()
    return results
 
def rank_nodes(nodes: list) -> list:
    """
    排序规则：
      1. hy2 节点排前面，按延迟升序
      2. 其他节点按延迟升序追加在后
      3. 超时（9999ms）的节点排最后
    """
    hy2   = sorted([n for n in nodes if n["proto"] == "hysteria2"], key=lambda x: x["latency_ms"])
    other = sorted([n for n in nodes if n["proto"] != "hysteria2"], key=lambda x: x["latency_ms"])
    return hy2 + other
 
# ─────────────────────────────────────────────────────────────────────────────
#  状态文件读写
# ─────────────────────────────────────────────────────────────────────────────
 
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except: return {}
 
def save_state(state: dict):
    os.makedirs(XRAY_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
 
# ─────────────────────────────────────────────────────────────────────────────
#  系统服务控制
# ─────────────────────────────────────────────────────────────────────────────
 
def restart_xray():
    r = subprocess.run(["systemctl", "restart", XRAY_SVC],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  [✓] systemctl restart {XRAY_SVC}")
    else:
        print(f"  [!] restart 失败: {r.stderr.strip()}")
    return r.returncode == 0
 
def apply_node(node_file: str):
    """将指定节点 JSON 复制到 config.json 并重启 xray。"""
    src = os.path.join(NODES_DIR, node_file)
    if not os.path.exists(src):
        print(f"  [✗] 节点文件不存在: {src}")
        return False
    shutil.copy2(src, CONFIG)
    print(f"  [→] 应用节点: {node_file}")
    return restart_xray()
 
# ─────────────────────────────────────────────────────────────────────────────
#  健康检查
# ─────────────────────────────────────────────────────────────────────────────
 
def health_check() -> bool:
    """
    通过本地 socks 代理访问 HEALTH_URL，
    返回 HTTP 204 视为健康，否则为故障。
    """
    try:
        result = subprocess.run(
            ["curl", "--socks5", f"127.0.0.1:{SOCKS_PORT}",
             "--max-time", str(HEALTH_TIMEOUT),
             "-s", "-o", "/dev/null",
             "-w", "%{http_code}",
             HEALTH_URL],
            capture_output=True, text=True, timeout=HEALTH_TIMEOUT + 3
        )
        code = result.stdout.strip()
        return code == "204"
    except Exception:
        return False
 
# ─────────────────────────────────────────────────────────────────────────────
#  文件名工具
# ─────────────────────────────────────────────────────────────────────────────
 
def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\s\-.]", "_", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:80] or "node"
 
# ─────────────────────────────────────────────────────────────────────────────
#  子命令实现
# ─────────────────────────────────────────────────────────────────────────────
 
def cmd_update(sub_url: str | None):
    """拉取订阅 → 解析 → 覆盖写入 nodes/ → 测速 → 排名 → 应用最佳节点。"""
    state = load_state()
    if not sub_url:
        sub_url = state.get("sub_url")
    if not sub_url:
        print("[✗] 请提供订阅地址: xray-manager update <URL>")
        sys.exit(1)
 
    print(f"[*] 拉取订阅: {sub_url}")
    content = fetch_sub(sub_url)
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    print(f"[*] 发现 {len(lines)} 行")
 
    # 清空旧节点目录
    os.makedirs(NODES_DIR, exist_ok=True)
    for f in os.listdir(NODES_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(NODES_DIR, f))
 
    # 解析并写入
    parsed_nodes = []
    skip = 0
    for idx, line in enumerate(lines, 1):
        ob, host, name = parse_node(line)
        if ob is None:
            proto = line.split("://")[0] if "://" in line else "?"
            print(f"  [{idx:03d}] ⚠ 跳过 ({proto})")
            skip += 1
            continue
 
        proto = ob["protocol"]
        # 区分 hy2 和 hy1
        if proto == "hysteria":
            proto = "hysteria2" if ob["settings"].get("version",0) == 2 else "hysteria"
 
        fname = f"{idx:03d}_{safe_name(name)}.json"
        cfg = build_config(idx, ob, host)
        with open(os.path.join(NODES_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
 
        parsed_nodes.append({"file": fname, "proto": proto,
                              "name": name, "host": host})
        print(f"  [{idx:03d}] [{proto:10s}] {name}")
 
    print(f"\n[*] 解析完成: {len(parsed_nodes)} 成功 / {skip} 跳过")
    print(f"[*] 测速中（ping × {PING_COUNT}，并发）……")
    ranked = rank_nodes(measure_all(parsed_nodes))
 
    print(f"\n[*] 排名结果（hy2 优先）:")
    for i, n in enumerate(ranked):
        ms = n["latency_ms"]
        ms_str = f"{ms:.0f} ms" if ms < 9999 else "超时"
        marker = " ←── 将应用" if i == 0 else ""
        print(f"  #{i+1:02d} [{n['proto']:10s}] {ms_str:8s}  {n['name']}{marker}")
 
    # 保存状态
    state = {
        "sub_url":       sub_url,
        "ranked_nodes":  ranked,
        "current_index": 0,
        "fail_count":    0,
        "updated_at":    datetime.now().isoformat(timespec="seconds"),
    }
    save_state(state)
 
    # 应用最佳节点
    if ranked:
        print(f"\n[*] 应用最佳节点: {ranked[0]['name']}")
        apply_node(ranked[0]["file"])
    else:
        print("[✗] 无可用节点")
 
 
def cmd_check():
    """
    健康检查。
    连续失败 MAX_FAIL_COUNT 次后自动切换到下一节点。
    通常由 systemd timer 每分钟调用一次。
    """
    state = load_state()
    if not state.get("ranked_nodes"):
        print("[!] 尚无节点数据，请先执行 update")
        sys.exit(1)
 
    ranked = state["ranked_nodes"]
    cur    = state.get("current_index", 0)
    fails  = state.get("fail_count", 0)
 
    cur_name = ranked[cur]["name"] if cur < len(ranked) else "未知"
    ok = health_check()
 
    if ok:
        if fails > 0:
            state["fail_count"] = 0
            save_state(state)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] ✓ 健康  当前节点: {cur_name}")
        return
 
    fails += 1
    state["fail_count"] = fails
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] ✗ 故障  当前节点: {cur_name}  (连续失败 {fails}/{MAX_FAIL_COUNT})")
 
    if fails >= MAX_FAIL_COUNT:
        next_idx = (cur + 1) % len(ranked)
        state["current_index"] = next_idx
        state["fail_count"]    = 0
        save_state(state)
        next_node = ranked[next_idx]
        print(f"  [→] 切换至第 {next_idx+1} 个节点: {next_node['name']}")
        apply_node(next_node["file"])
    else:
        save_state(state)
 
 
def cmd_switch(target=None):
    """手动切换节点。target 可为数字(1-based)或 'next'/'prev'。"""
    state = load_state()
    ranked = state.get("ranked_nodes", [])
    if not ranked:
        print("[✗] 尚无节点数据，请先执行 update"); sys.exit(1)
 
    cur = state.get("current_index", 0)
    n   = len(ranked)
 
    if target is None or target == "next":
        idx = (cur + 1) % n
    elif target == "prev":
        idx = (cur - 1) % n
    else:
        try:
            idx = int(target) - 1
            if not (0 <= idx < n):
                print(f"[✗] 序号超出范围 1-{n}"); sys.exit(1)
        except ValueError:
            print(f"[✗] 无效参数: {target}"); sys.exit(1)
 
    state["current_index"] = idx
    state["fail_count"]    = 0
    save_state(state)
    node = ranked[idx]
    print(f"[*] 切换到第 {idx+1} 个节点: [{node['proto']}] {node['name']}")
    apply_node(node["file"])
 
 
def cmd_list():
    """显示所有节点排名。"""
    state = load_state()
    ranked = state.get("ranked_nodes", [])
    if not ranked:
        print("尚无节点数据，请先执行 update"); return
    cur = state.get("current_index", 0)
    print(f"{'#':>4}  {'协议':<12} {'延迟':>8}  {'节点名称'}")
    print("─" * 70)
    for i, n in enumerate(ranked):
        ms = n["latency_ms"]
        ms_str = f"{ms:.0f} ms" if ms < 9999 else "超时"
        active = " ◀ 当前" if i == cur else ""
        print(f"  {i+1:02d}  {n['proto']:<12} {ms_str:>8}  {n['name']}{active}")
 

def fetch_ip_info():
    try:
        with urllib.request.urlopen("http://ip-api.com/json", timeout=3) as r:
            return json.loads(r.read().decode())
    except:
        return None

def cmd_status():
    """显示当前节点及实时健康状态。"""
    state = load_state()
    ranked = state.get("ranked_nodes", [])
    cur = state.get("current_index", 0)
    fails = state.get("fail_count", 0)
    updated = state.get("updated_at", "未知")
 
    if ranked and cur < len(ranked):
        node = ranked[cur]
        print(f"当前节点 : #{cur+1}  [{node['proto']}] {node['name']}")
        print(f"主机     : {node['host']}")
        print(f"延迟     : {node['latency_ms']:.0f} ms" if node['latency_ms'] < 9999 else "延迟     : 超时")
    else:
        print("当前节点 : 未知")
 
    print(f"连续失败 : {fails} / {MAX_FAIL_COUNT}")
    print(f"节点总数 : {len(ranked)}")
    print(f"上次更新 : {updated}")
    print(f"订阅地址 : {state.get('sub_url', '未设置')}")
    print()
    print("[*] 实时健康检查中……", end=" ", flush=True)
    ok = health_check()
    print("✓ 正常" if ok else "✗ 故障")
    # 出口 IP 信息
    print("[*] 查询出口 IP（ip-api.com）……")

    info = fetch_ip_info()

    if not info:
        print("✗ 查询失败")
        return
    print(info)
    
def cmd_install():
    """安装 systemd watchdog timer，每 60 秒自动执行一次 check。"""
    script_path = os.path.abspath(__file__)
 
    svc_content = f"""[Unit]
Description=Xray Node Health Watchdog (oneshot)
After=network.target
 
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script_path} check
StandardOutput=journal
StandardError=journal
"""
 
    timer_content = """[Unit]
Description=Xray Node Health Watchdog Timer
Requires=xray-watchdog.service
 
[Timer]
OnBootSec=90
OnUnitActiveSec=60
AccuracySec=10
 
[Install]
WantedBy=timers.target
"""
 
    svc_path   = "/etc/systemd/system/xray-watchdog.service"
    timer_path = "/etc/systemd/system/xray-watchdog.timer"
 
    try:
        with open(svc_path,   "w") as f: f.write(svc_content)
        with open(timer_path, "w") as f: f.write(timer_content)
        subprocess.run(["systemctl","daemon-reload"], check=True)
        subprocess.run(["systemctl","enable","--now","xray-watchdog.timer"], check=True)
        print(f"[✓] 已安装并启动 xray-watchdog.timer（每 60 秒健康检查）")
        print(f"    查看日志: journalctl -u xray-watchdog.service -f")
        print(f"    停止:     systemctl disable --now xray-watchdog.timer")
    except PermissionError:
        print("[✗] 需要 root 权限，请用 sudo 运行")
    except subprocess.CalledProcessError as e:
        print(f"[✗] systemctl 失败: {e}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  入口
# ─────────────────────────────────────────────────────────────────────────────
 
CMDS = {
    "update":  (cmd_update,  "update [URL]   拉取订阅，测速，应用最快 hy2 节点"),
    "check":   (cmd_check,   "check          健康检查，故障时自动切换"),
    "switch":  (cmd_switch,  "switch [N]     切换到第 N 个节点（默认下一个）"),
    "list":    (cmd_list,    "list           显示所有节点排名"),
    "status":  (cmd_status,  "status         显示当前节点与健康状态"),
    "install": (cmd_install, "install        安装 systemd 健康检查定时器"),
}
 
def main():
    args = sys.argv[1:]
    if not args or args[0] not in CMDS:
        print("用法: xray-manager <子命令> [参数]\n")
        for _, (_, desc) in CMDS.items():
            print(f"  {desc}")
        print()
        print("示例:")
        print("  xray-manager update https://example.com/sub/token")
        print("  xray-manager status")
        print("  xray-manager list")
        print("  xray-manager switch 3    # 切换到第3个节点")
        print("  sudo xray-manager install")
        sys.exit(0)
 
    cmd = args[0]
    fn, _ = CMDS[cmd]
 
    if cmd == "update":
        fn(args[1] if len(args) > 1 else None)
    elif cmd == "switch":
        fn(args[1] if len(args) > 1 else None)
    else:
        fn()
 
if __name__ == "__main__":
    main()