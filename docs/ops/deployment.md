# 部署指南

## 概述

本文档提供 Ralph 集成系统的完整部署指南，包括环境要求、安装步骤和配置说明。

---

## 目录

- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [详细安装](#详细安装)
- [生产部署](#生产部署)
- [升级指南](#升级指南)

---

## 环境要求

### 最低配置

| 组件 | 要求 |
|------|------|
| **操作系统** | Linux (Ubuntu 20.04+, Debian 11+, CentOS 8+) |
| **CPU** | 2 核 |
| **内存** | 4 GB |
| **磁盘** | 20 GB |
| **网络** | 稳定的互联网连接 |

### 推荐配置

| 组件 | 要求 |
|------|------|
| **操作系统** | Linux (Ubuntu 22.04 LTS) |
| **CPU** | 4 核以上 |
| **内存** | 8 GB 以上 |
| **磁盘** | 50 GB 以上 SSD |
| **网络** | 稳定的互联网连接（GitHub API 访问） |

### 软件依赖

| 软件 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.8+ | 运行 Python 组件 |
| **Git** | 2.30+ | 版本控制 |
| **Node.js** | 18+ | 运行 Dashboard（可选） |
| **Bun** | 1.0+ | TypeScript 项目质量检查 |
| **Claude Code CLI** | 最新 | AI 编码工具 |
| **SQLite** | 3.35+ | 数据库 |

---

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/user01/ai-devops.git
cd ai-devops
```

### 2. 安装依赖

```bash
# Python 依赖
pip install -r requirements.txt

# 或使用 Poetry
poetry install
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，设置必要的变量
nano .env
```

### 4. 初始化数据库

```bash
python3 orchestrator/bin/ralph_state.py stats
```

### 5. 运行测试

```bash
# 运行单元测试
python3 -m pytest tests/

# 运行集成测试
python3 -m pytest tests/ -m integration
```

### 6. 启动服务

```bash
# 启动 Dashboard（如果使用）
npm install
npm run dev

# 启动 API Server
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 详细安装

### 1. 安装 Python

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

**CentOS/RHEL:**

```bash
sudo yum install python3 python3-pip
```

**macOS:**

```bash
brew install python@3
```

### 2. 创建虚拟环境

```bash
cd ai-devops
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**主要依赖：**

```txt
fastapi==0.104.0
uvicorn[standard]==0.24.0
pydantic==2.5.0
github.py==1.59.1
websockets==12.0
python-frontmatter==1.0.0
pytest==7.4.3
pytest-cov==4.1.0
```

### 4. 安装 Node.js 和 Bun

**安装 Node.js:**

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# macOS
brew install node
```

**安装 Bun:**

```bash
curl -fsSL https://bun.sh/install | bash
```

### 5. 安装 Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
```

验证安装：

```bash
claude --version
```

### 6. 配置 GitHub 访问

```bash
# 生成 Personal Access Token
# 访问：https://github.com/settings/tokens

# 设置环境变量
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 7. 验证安装

```bash
# 检查 Python 版本
python3 --version

# 检查依赖
pip list | grep -E "fastapi|github|websockets"

# 检查数据库
sqlite3 --version

# 检查 Claude CLI
claude --version
```

---

## 生产部署

### 1. 使用 Systemd

**创建服务文件：**

```bash
sudo nano /etc/systemd/system/ralph-api.service
```

**服务文件内容：**

```ini
[Unit]
Description=Ralph API Server
After=network.target

[Service]
Type=simple
User=ralph
WorkingDirectory=/opt/ai-devops
Environment="PATH=/opt/ai-devops/venv/bin"
EnvironmentFile=/opt/ai-devops/.env
ExecStart=/opt/ai-devops/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**启动服务：**

```bash
sudo systemctl daemon-reload
sudo systemctl enable ralph-api
sudo systemctl start ralph-api
sudo systemctl status ralph-api
```

### 2. 使用 Docker

**创建 Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 创建非 root 用户
RUN useradd -m -u 1000 ralph && chown -R ralph:ralph /app
USER ralph

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**创建 docker-compose.yml:**

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - RALPH_DB_PATH=/data/agent_tasks.db
    volumes:
      - ./data:/data
      - ./logs:/app/logs
    restart: unless-stopped

  dashboard:
    build: ./dashboard
    ports:
      - "3000:3000"
    depends_on:
      - api
    restart: unless-stopped
```

**启动：**

```bash
docker-compose up -d
```

### 3. 使用 Nginx 反向代理

**配置 Nginx:**

```nginx
server {
    listen 80;
    server_name ralph.example.com;

    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://localhost:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**重启 Nginx:**

```bash
sudo nginx -t
sudo systemctl restart nginx
```

### 4. 配置 HTTPS

**使用 Let's Encrypt:**

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ralph.example.com
```

---

## 升级指南

### 1. 备份数据

```bash
# 备份数据库
cp agent_tasks.db agent_tasks.db.backup.$(date +%Y%m%d)

# 备份配置
cp .env .env.backup.$(date +%Y%m%d)
```

### 2. 拉取最新代码

```bash
git fetch origin main
git checkout main
git pull origin main
```

### 3. 更新依赖

```bash
pip install --upgrade -r requirements.txt
```

### 4. 数据库迁移

```bash
python3 scripts/migrate_db.py --from old_schema --to new_schema
```

### 5. 重启服务

```bash
# Systemd
sudo systemctl restart ralph-api

# Docker
docker-compose down
docker-compose up -d
```

### 6. 验证升级

```bash
# 检查 API
curl http://localhost:8000/api/v1/stats

# 检查日志
sudo journalctl -u ralph-api -f
```

---

## 故障排查

### 问题：模块导入失败

**症状：**

```
ModuleNotFoundError: No module named 'fastapi'
```

**解决方案：**

```bash
# 激活虚拟环境
source venv/bin/activate

# 重新安装依赖
pip install -r requirements.txt
```

### 问题：数据库权限错误

**症状：**

```
sqlite3.OperationalError: unable to open database file
```

**解决方案：**

```bash
# 检查文件权限
ls -la agent_tasks.db

# 修改权限
chmod 644 agent_tasks.db
chown ralph:ralph agent_tasks.db
```

### 问题：端口已被占用

**症状：**

```
OSError: [Errno 98] Address already in use
```

**解决方案：**

```bash
# 查找占用端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或更改端口
uvicorn main:app --port 8001
```

### 问题：GitHub API 限流

**症状：**

```
github.GithubException: 403 {"message": "API rate limit exceeded"}
```

**解决方案：**

```bash
# 生成新的 Personal Access Token
# 访问：https://github.com/settings/tokens

# 更新环境变量
export GITHUB_TOKEN="ghp_new_token"
```

---

## 最佳实践

1. **使用虚拟环境**：避免 Python 依赖冲突
2. **定期备份**：自动备份数据库和配置
3. **监控日志**：使用日志聚合工具（如 ELK）
4. **版本控制**：跟踪配置文件的变更
5. **安全加固**：限制 API 访问，使用 HTTPS
6. **资源限制**：设置 CPU 和内存限制
7. **健康检查**：配置自动健康检查和重启

---

## 参考文档

- [配置参考](./configuration.md)
- [监控指南](./monitoring.md)
- [故障排查](./troubleshooting.md)
- [备份和恢复](./backup-restore.md)
