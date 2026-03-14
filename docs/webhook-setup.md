# GitHub Webhook 配置指南

## 概述

Webhook 服务器接收 GitHub 事件（check_run、workflow_run、pull_request），并自动触发 monitor 检查任务状态。

**优势:**
- 事件驱动，无需轮询
- PR 状态更新延迟从 30s 降至秒级
- 节省 99% GitHub API 配额

---

## 架构

```
GitHub ──webhook──> webhook_server.py:8080 ──trigger──> monitor.py --once
                                                      │
                                                      ▼
                                              SQLite (agent_tasks.db)
```

---

## 部署

### Linux (systemd)

**1. 编辑服务文件**

```bash
# 替换路径和密钥
sed -i 's|/home/user01|'$HOME'|g' ~/ai-devops/ai-devops-webhook.service
sed -i 's/CHANGE_ME_SECRET_KEY/'$(openssl rand -hex 16)'/' ~/ai-devops/ai-devops-webhook.service
```

**2. 安装服务**

```bash
sudo cp ~/ai-devops/ai-devops-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-devops-webhook
sudo systemctl start ai-devops-webhook
```

**3. 验证状态**

```bash
systemctl status ai-devops-webhook
journalctl -u ai-devops-webhook -f
```

---

### macOS (launchd)

**1. 编辑 plist 文件**

```bash
# 替换路径和密钥
sed -i '' 's|/Users/gordon|'$HOME'|g' ~/ai-devops/com.ai-devops.webhook.plist

# 生成随机密钥
SECRET=$(openssl rand -hex 16)
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:GITHUB_WEBHOOK_SECRET $SECRET" ~/ai-devops/com.ai-devops.webhook.plist
```

**2. 注册 launchd**

```bash
ln -sf ~/ai-devops/com.ai-devops.webhook.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ai-devops.webhook.plist
```

**3. 验证状态**

```bash
launchctl list | grep ai-devops.webhook
tail -f ~/ai-devops/logs/webhook-stdout.log
```

---

### 手动运行（测试）

```bash
# 前台运行
cd ~/ai-devops
python3 orchestrator/bin/webhook_server.py --port 8080 --secret my-secret

# 后台运行
python3 orchestrator/bin/webhook_server.py --port 8080 --secret my-secret --daemon
```

---

## GitHub 配置

### 1. 创建 Webhook

**导航:** Repository Settings → Webhooks → Add webhook

### 2. 配置参数

| 字段 | 值 |
|------|-----|
| **Payload URL** | `http://<your-server-ip>:8080/` |
| **Content type** | `application/json` |
| **Secret** | `<your-secret-key>` |
| **SSL verification** | Disabled (if using HTTP) |

### 3. 选择事件

选择 **Let me select individual events**:

- ✅ Check runs
- ✅ Workflow runs  
- ✅ Pull requests

或者选择 **Send me everything**.

### 4. 保存

点击 **Add webhook**.

---

## 测试

### 1. 健康检查

```bash
curl http://localhost:8080/health
```

**响应:**
```json
{
  "status": "healthy",
  "timestamp": 1773414400000,
  "base_dir": "/home/user01/ai-devops"
}
```

### 2. 使用测试脚本

```bash
# 测试所有事件
python3 orchestrator/bin/test_webhook.py --port 8080 --event all

# 只测试 check_run
python3 orchestrator/bin/test_webhook.py --port 8080 --event check_run
```

### 3. 手动触发（curl）

```bash
# 生成签名
SECRET="my-secret"
PAYLOAD='{"action":"completed","check_run":{"name":"test","conclusion":"success","head_branch":"feat/test"}}'
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print "sha256="$2}')

# 发送请求
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-Hub-Signature-256: $SIGNATURE" \
  -d "$PAYLOAD"
```

---

## 支持的事件

### check_run

**触发:** CI 检查完成时

**Payload 示例:**
```json
{
  "action": "completed",
  "check_run": {
    "name": "test",
    "status": "completed",
    "conclusion": "success",
    "head_branch": "feat/my-feature",
    "html_url": "https://github.com/..."
  }
}
```

**处理逻辑:**
1. 提取 `head_branch`
2. 查找匹配的任务
3. 触发 monitor 检查

---

### workflow_run

**触发:** GitHub Actions 工作流完成时

**Payload 示例:**
```json
{
  "action": "completed",
  "workflow_run": {
    "name": "CI",
    "status": "completed",
    "conclusion": "failure",
    "head_branch": "feat/my-feature",
    "id": 12345,
    "html_url": "https://github.com/..."
  }
}
```

**处理逻辑:** 同 check_run

---

### pull_request

**触发:** PR 打开/关闭时

**Payload 示例:**
```json
{
  "action": "opened",
  "pull_request": {
    "number": 42,
    "state": "open",
    "merged": false,
    "head": {
      "ref": "feat/my-feature"
    },
    "html_url": "https://github.com/..."
  }
}
```

**处理逻辑:**
- `opened`: 更新任务 PR 信息
- `closed` + `merged=true`: 标记任务为 merged
- `closed` + `merged=false`: 标记任务为 pr_closed

---

## 日志

### Webhook 日志

```bash
# 实时查看
tail -f ~/ai-devops/logs/webhook.log

# 查看最近事件
cat ~/ai-devops/logs/webhook.log | tail -20 | jq .
```

### 服务日志

```bash
# systemd (Linux)
journalctl -u ai-devops-webhook -f

# launchd (macOS)
tail -f ~/ai-devops/logs/webhook-stdout.log
tail -f ~/ai-devops/logs/webhook-stderr.log
```

---

## 故障排查

### 问题 1: Webhook 不触发

**检查:**
1. GitHub webhook 状态（Settings → Webhooks）
2. 查看 Recent Deliveries
3. 检查防火墙规则

```bash
# 检查端口监听
netstat -tlnp | grep 8080
ss -tlnp | grep 8080

# 检查防火墙
sudo ufw status
sudo iptables -L -n | grep 8080
```

### 问题 2: 签名验证失败

**日志:**
```
[WARN] Invalid signature from <IP>
```

**解决:**
1. 确认 GitHub 配置的 Secret 与服务端一致
2. 检查环境变量 `GITHUB_WEBHOOK_SECRET`

```bash
# 验证配置
echo $GITHUB_WEBHOOK_SECRET
systemctl cat ai-devops-webhook | grep SECRET
```

### 问题 3: Monitor 未触发

**日志:**
```
[INFO] Found task: <task-id>
[INFO] Monitor triggered successfully
```

**检查:**
```bash
# 查看 monitor 日志
tail -f ~/ai-devops/logs/monitor-stdout.log

# 手动触发 monitor
python3 ~/ai-devops/orchestrator/bin/monitor.py --once
```

---

## 安全建议

### 1. 使用 HTTPS（生产环境）

```bash
# 使用 nginx 反向代理 + Let's Encrypt
server {
    listen 443 ssl;
    server_name webhook.example.com;
    
    ssl_certificate /etc/letsencrypt/live/webhook.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/webhook.example.com/privkey.pem;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. 限制访问 IP

```bash
# 只允许 GitHub IPs
sudo ufw allow from 140.82.112.0/20 to any port 8080
sudo ufw allow from 140.82.113.0/20 to any port 8080
# ... 添加其他 GitHub IP 段
```

### 3. 使用强密钥

```bash
# 生成 32 字节随机密钥
openssl rand -hex 32
```

---

## 性能优化

### 1. 调整并发

Webhook 服务器是单线程的。如需高并发：

```bash
# 使用 gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8080 webhook_server:app
```

### 2. 批量触发

多个 webhook 同时到达时，合并 monitor 触发：

```python
# 添加 debounce 逻辑（待实现）
```

---

## 监控指标

### 关键指标

| 指标 | 说明 | 告警阈值 |
|------|------|----------|
| webhook 请求数 | 接收的事件数量 | - |
| 平均响应时间 | 处理延迟 | > 5s |
| monitor 触发次数 | 触发的检查次数 | - |
| 签名失败次数 | 验证失败数量 | > 10/min |

### 日志分析

```bash
# 统计事件类型
cat webhook.log | jq -r '.event' | sort | uniq -c

# 统计结论分布
cat webhook.log | jq -r '.data.conclusion' | sort | uniq -c

# 查找错误
grep ERROR webhook.log
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `orchestrator/bin/webhook_server.py` | Webhook 服务器 |
| `orchestrator/bin/test_webhook.py` | 测试脚本 |
| `ai-devops-webhook.service` | systemd 配置 |
| `com.ai-devops.webhook.plist` | launchd 配置 |
| `logs/webhook.log` | 事件日志 |
