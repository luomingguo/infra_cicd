#!/usr/bin/env bash
curl -fsSL https://get.docker.com -o get-docker.sh | sh
sudo mkdir -p /etc/apt/keyrings
curl -fsSL -x http://127.0.0.1:10808 https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get -o Acquire::http::Proxy="http://127.0.0.1:10808" -o Acquire::https::Proxy="http://127.0.0.1:10808" update
sudo apt-get -o Acquire::http::Proxy="http://127.0.0.1:10808" -o Acquire::https::Proxy="http://127.0.0.1:10808" install -y docker-compose-plugin
docker compose versionx