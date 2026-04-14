# 故障排查

## 概述

本文档提供 Ralph 集成系统的常见问题和解决方案。

---

## 目录

- [启动问题](#启动问题)
- [执行问题](#执行问题)
- [数据库问题](#数据库问题)
- [API 问题](#api-问题)
- [质量检查问题](#质量检查问题)
- [性能问题](#性能问题)
- [网络问题](#网络问题)

---

## 启动问题

### 问题：ModuleNotFoundError

**症状：**

```
ModuleNotFoundError: No module named 'fastapi'
```

**原因：** Python 依赖未安装或虚拟环境未激活

**解决方案：**

```bash
# 激活虚拟环境
source venv/bin/activate

# 重新安装依赖
pip install -r requirements.txt

# 或使用 Poetry
poetry install
```

---

### 问题：端口已被占用

**症状：**

```
OSError: [Errno 98] Address already in use
```

**原因：** 端口 8000 已被其他进程占用

**解决方案：**

```bash
# 查找占用端口的进程
lsof -i :8000

# 或使用 netstat
netstat -tulpn | grep :8000

# 杀死进程
kill -9 <PID>

# 或更改端口
uvicorn main:app --port 8001
```

---

### 问题：权限不足

**症状：**

```
Permission denied: '/var/log/ralph/ralph.log'
```

**原因：** 日志目录权限不足

**解决方案：**

```bash
# 创建日志目录并设置权限
sudo mkdir -p /var/log/ralph
sudo chown -R ralph:ralph /var/log/ralph
sudo chmod 755 /var/log/ralph

# 检查当前用户
whoami
# 应该是 ralph 用户

# 如果不是，切换用户
sudo -u ralph -H sh -c "source venv/bin/activate && uvicorn main:app"
```

---

### 问题：环境变量未设置

**症状：**

```
KeyError: 'GITHUB_TOKEN'
```

**原因：** 环境变量未正确设置

**解决方案：**

```bash
# 检查环境变量
echo $GITHUB_TOKEN

# 临时设置
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 永久设置（添加到 ~/.bashrc）
echo 'export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"' >> ~/.bashrc
source ~/.bashrc

# 或使用 .env 文件
echo 'GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' > .env
```

---

## 执行问题

### 问题：ralph.sh not found

**症状：**

```
FileNotFoundError: ralph.sh not found
```

**原因：** ralph.sh 路径不正确或文件不存在

**解决方案：**

```bash
# 检查文件是否存在
ls -la ~/.openclaw/workspace-alpha/ralph/ralph.sh

# 如果不存在，创建符号链接
ln -s /path/to/ralph/ralph.sh ~/.openclaw/workspace-alpha/ralph/ralph.sh

# 或在代码中指定正确路径
runner = RalphRunner(
    ralph_dir="/tmp/ralph-task-001",
    ralph_sh_path="/custom/path/ralph.sh"
)
```

---

### 问题：执行超时

**症状：**

```
subprocess.TimeoutExpired: Command 'ralph.sh' timed out after 7200 seconds
```

**原因：** 任务执行时间超过默认超时时间

**解决方案：**

```python
# 增加超时时间
runner.run(
    max_iterations=10,
    timeout=10800  # 3 小时
)

# 或在配置文件中设置
# .env
RALPH_TIMEOUT=10800
```

---

### 问题：进程被杀死

**症状：**

```
Process finished with exit code -9
```

**原因：** 系统内存不足，OOM Killer 杀死进程

**解决方案：**

```bash
# 检查内存使用
free -h

# 查看 OOM 日志
sudo dmesg | grep -i "killed process"

# 增加交换空间
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 或限制 Ralph 进程内存
ulimit -v 4194304  # 4GB
```

---

### 问题：无限循环

**症状：** Ralph 持续执行，无法完成

**原因：** AI 陷入循环，无法完成任务

**解决方案：**

```python
# 设置最大迭代次数
runner.run(
    max_iterations=15,  # 增加迭代次数
    timeout=10800
)

# 或手动终止
runner.terminate()

# 检查 progress.txt
cat /tmp/ralph-task-001/progress.txt
```

---

## 数据库问题

### 问题：数据库锁定

**症状：**

```
sqlite3.OperationalError: database is locked
```

**原因：** 多个进程同时访问数据库

**解决方案：**

```python
# 启用 WAL 模式
conn = sqlite3.connect('agent_tasks.db')
conn.execute("PRAGMA journal_mode=WAL")
conn.commit()

# 增加超时时间
conn = sqlite3.connect('agent_tasks.db', timeout=30)

# 或使用连接池
from sqlite3 import connect

pool = RalphState(db_path="agent_tasks.db", pool_size=5, timeout=30)
```

---

### 问题：数据库损坏

**症状：**

```
sqlite3.DatabaseError: database disk image is malformed
```

**原因：** 数据库文件损坏

**解决方案：**

```bash
# 备份当前数据库
cp agent_tasks.db agent_tasks.db.corrupted

# 尝试修复
sqlite3 agent_tasks.db "PRAGMA integrity_check;"

# 如果损坏，恢复备份
cp agent_tasks.db.backup.20260414 agent_tasks.db

# 或使用 sqlite3 恢复
sqlite3 agent_tasks.db ".recover" | sqlite3 agent_tasks_recovered.db
```

---

### 问题：UNIQUE constraint failed

**症状：**

```
sqlite3.IntegrityError: UNIQUE constraint failed: ralph_state.task_id
```

**原因：** 尝试创建已存在的任务

**解决方案：**

```python
# 检查任务是否已存在
task = state.get("task-001")
if task is not None:
    print(f"Task {task_id} already exists")
else:
    state.create(task_id="task-001", status="queued")
```

---

### 问题：查询缓慢

**症状：** 数据库查询响应时间过长

**原因：** 缺少索引或数据量过大

**解决方案：**

```sql
-- 添加索引
CREATE INDEX idx_status ON ralph_state(status);
CREATE INDEX idx_updated_at ON ralph_state(updated_at);
CREATE INDEX idx_status_updated ON ralph_state(status, updated_at);

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT * FROM ralph_state WHERE status = 'running';

-- 清理数据库
VACUUM;
ANALYZE;
```

---

## API 问题

### 问题：404 Not Found

**症状：**

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task task-001 not found"
  }
}
```

**原因：** 任务不存在或路径错误

**解决方案：**

```bash
# 检查任务是否存在
./ralph_state.py get task-001

# 检查 API 路径
curl http://localhost:8000/api/v1/tasks/task-001

# 检查任务 ID 格式
# 应该是 task-YYYYMMDD-NNN 格式
```

---

### 问题：401 Unauthorized

**症状：**

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or missing token"
  }
}
```

**原因：** 缺少认证或 token 无效

**解决方案：**

```bash
# 检查 token
echo $GITHUB_TOKEN

# 在请求头中包含 token
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  http://localhost:8000/api/v1/tasks
```

---

### 问题：429 Too Many Requests

**症状：**

```
HTTP/1.1 429 Too Many Requests
```

**原因：** 超过速率限制

**解决方案：**

```python
# 等待后重试
import time
time.sleep(60)  # 等待 60 秒

# 或在配置中调整速率限制
# .env
RALPH_RATE_LIMIT_ENABLED=false
```

---

### 问题：500 Internal Server Error

**症状：** 服务器返回 500 错误

**原因：** 服务器内部错误

**解决方案：**

```bash
# 查看服务器日志
tail -f /var/log/ralph/ralph.log
journalctl -u ralph-api -f

# 检查错误堆栈
# 在日志中查找 Traceback
grep -i "traceback" /var/log/ralph/ralph.log
```

---

## 质量检查问题

### 问题：Typecheck 失败

**症状：**

```
typecheck: failed with exit code 1
```

**原因：** TypeScript 类型错误

**解决方案：**

```bash
# 查看详细错误
bun run typecheck

# 修复类型错误
# 根据错误提示修复代码
```

---

### 问题：Lint 失败

**症状：**

```
lint: failed with exit code 1
```

**原因：** 代码风格不符合规范

**解决方案：**

```bash
# 查看详细错误
bun run lint

# 自动修复部分问题
bun run lint --fix

# 检查 lint 配置
cat .eslintrc
```

---

### 问题：测试失败

**症状：**

```
test: failed with exit code 1
```

**原因：** 单元测试失败

**解决方案：**

```bash
# 查看详细错误
bun run test

# 运行特定测试
bun run test --testNamePattern="testSpecific"

# 查看覆盖率
bun run test:coverage
```

---

### 问题：CI 检查失败

**症状：** GitHub Actions 检查失败

**原因：** CI 配置或环境问题

**解决方案：**

```bash
# 查看 GitHub Actions 日志
# 访问：https://github.com/user01/ai-devops/actions

# 本地模拟 CI 环境
docker-compose run --rm ci

# 检查 CI 配置
cat .github/workflows/ralph-quality.yml
```

---

## 性能问题

### 问题：CPU 使用率过高

**症状：** CPU 使用率持续超过 90%

**原因：** AI 编码过程或未优化的代码

**解决方案：**

```bash
# 查看进程 CPU 使用
top -p $(pgrep -f ralph)

# 使用 htop
htop

# 限制 CPU 使用
cpulimit -l 200 -p $(pgrep -f ralph)

# 或使用 nice 降低优先级
nice -n 10 python3 main.py
```

---

### 问题：内存泄漏

**症状：** 内存使用持续增长

**原因：** 未释放的资源或内存泄漏

**解决方案：**

```bash
# 查看内存使用
free -h
pmap -x $(pgrep -f ralph)

# 使用内存分析工具
python -m memory_profiler script.py

# 重启服务
systemctl restart ralph-api
```

---

### 问题：磁盘空间不足

**症状：** 磁盘使用率超过 90%

**原因：** 日志文件或临时文件过多

**解决方案：**

```bash
# 查看磁盘使用
df -h

# 查找大文件
find /var/log/ralph -type f -size +100M -exec ls -lh {} \;

# 清理旧日志
find /var/log/ralph -name "*.log" -mtime +7 -delete

# 清理数据库 WAL 文件
sqlite3 agent_tasks.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 或使用 logrotate
logrotate -f /etc/logrotate.d/ralph
```

---

## 网络问题

### 问题：GitHub API 限流

**症状：**

```
github.GithubException: 403 {"message": "API rate limit exceeded"}
```

**原因：** 超过 GitHub API 速率限制

**解决方案：**

```bash
# 查看剩余配额
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/rate_limit

# 生成新的 Personal Access Token
# 访问：https://github.com/settings/tokens

# 更新 token
export GITHUB_TOKEN="ghp_new_token"
```

---

### 问题：WebSocket 连接断开

**症状：** WebSocket 连接频繁断开

**原因：** 网络不稳定或服务器超时

**解决方案：**

```javascript
// 客户端重连逻辑
let reconnectInterval = 1000;
let maxReconnectInterval = 30000;

function connect() {
  const ws = new WebSocket('ws://localhost:8000/ws/tasks');

  ws.onclose = () => {
    console.log('WebSocket closed, reconnecting...');
    setTimeout(() => {
      connect();
      reconnectInterval = Math.min(reconnectInterval * 2, maxReconnectInterval);
    }, reconnectInterval);
  };
}
```

---

### 问题：DNS 解析失败

**症状：**

```
requests.exceptions.ConnectionError: DNS lookup failed
```

**原因：** DNS 配置问题或网络问题

**解决方案：**

```bash
# 检查 DNS 配置
cat /etc/resolv.conf

# 使用公共 DNS
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf

# 测试 DNS
nslookup github.com
dig github.com
```

---

## 调试技巧

### 1. 启用调试模式

```bash
# 设置日志级别
export RALPH_LOG_LEVEL=DEBUG

# 或在代码中设置
logging.basicConfig(level=logging.DEBUG)
```

### 2. 使用断点调试

```python
import pdb; pdb.set_trace()
# 或使用 ipdb
import ipdb; ipdb.set_trace()
```

### 3. 打印详细堆栈

```python
import traceback

try:
    # 你的代码
except Exception as e:
    traceback.print_exc()
```

### 4. 使用日志追踪

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")
```

---

## 寻求帮助

如果以上解决方案无法解决你的问题：

1. **收集日志**

```bash
# 应用日志
tar -czf ralph-logs-$(date +%Y%m%d).tar.gz /var/log/ralph/

# 系统日志
journalctl -u ralph-api --since "1 hour ago" > ralph-system.log
```

2. **检查版本**

```bash
python3 --version
pip list | grep -E "fastapi|github|websockets"
```

3. **提交 Issue**

在 GitHub 上提交 Issue，包含：
- 问题描述
- 复现步骤
- 日志文件
- 系统环境

---

## 参考文档

- [部署指南](./deployment.md)
- [配置参考](./configuration.md)
- [监控指南](./monitoring.md)
