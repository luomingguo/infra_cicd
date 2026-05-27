#!/usr/bin/env bash
# 离线下载
printf '\n' | ./install-release.sh --local /root/Xray-linux-64.zip

echo 'export all_proxy="socks5://127.0.0.1:10808"' >> ~/.bashrc
echo 'export http_proxy="http://127.0.0.1:10808"' >> ~/.bashrc
echo 'export https_proxy="http://127.0.0.1:10808"' >> ~/.bashrc
source ~/.bashrc