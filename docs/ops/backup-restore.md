# 备份和恢复

## 概述

本文档提供 Ralph 集成系统的数据备份和恢复指南。

---

## 目录

- [备份策略](#备份策略)
- [数据库备份](#数据库备份)
- [配置备份](#配置备份)
- [日志备份](#日志备份)
- [恢复流程](#恢复流程)
- [自动化备份](#自动化备份)

---

## 备份策略

### 备份类型

| 类型 | 内容 | 频率 | 保留期 |
|------|------|------|--------|
| **完全备份** | 所有数据 | 每天 | 7 天 |
| **增量备份** | 变更数据 | 每小时 | 1 天 |
| **日志备份** | 日志文件 | 每天 | 30 天 |
| **配置备份** | 配置文件 | 每周 | 永久 |

### 备份位置

1. **本地备份**: `/backup/ralph/`
2. **远程备份**: S3, Azure Blob, GCS
3. **异地备份**: 另一个数据中心

### 备份最佳实践

1. **3-2-1 原则**:
   - 3 份备份
   - 2 种不同介质
   - 1 份异地备份

2. **定期测试恢复**: 每月测试一次恢复流程

3. **加密备份**: 敏感数据加密存储

4. **版本控制**: 配置文件使用 Git 追踪

---

## 数据库备份

### 手动备份

**导出数据库：**

```bash
# 导出为 SQL 文件
sqlite3 agent_tasks.db .dump > backup_$(date +%Y%m%d).sql

# 压缩备份
gzip backup_$(date +%Y%m%d).sql

# 或直接复制数据库文件
cp agent_tasks.db agent_tasks.db.backup.$(date +%Y%m%d)
```

**导入数据库：**

```bash
# 从 SQL 恢复
sqlite3 agent_tasks.db < backup_20260414.sql

# 从备份文件恢复
cp agent_tasks.db.backup.20260414 agent_tasks.db
```

### 自动备份脚本

**backup_db.sh:**

```bash
#!/bin/bash
# backup_db.sh

BACKUP_DIR="/backup/ralph/db"
DB_PATH="agent_tasks.db"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 导出数据库
sqlite3 "$DB_PATH" ".backup $BACKUP_DIR/ralph_$DATE.db"

# 压缩备份
gzip -f "$BACKUP_DIR/ralph_$DATE.db"

# 删除 7 天前的备份
find "$BACKUP_DIR" -name "ralph_*.db.gz" -mtime +7 -delete

echo "Backup completed: ralph_$DATE.db.gz"
```

**设置定时任务：**

```bash
# 编辑 crontab
crontab -e

# 添加定时任务（每天凌晨 2 点）
0 2 * * * /opt/ai-devops/scripts/backup_db.sh >> /var/log/ralph/backup.log 2>&1
```

### 使用 WAL 模式

```sql
-- 启用 WAL 模式（更好的并发性能）
PRAGMA journal_mode=WAL;

-- 备份 WAL 文件
cp agent_tasks.db-wal agent_tasks.db-wal.backup
```

---

## 配置备份

### 手动备份

```bash
# 备份 .env 文件
cp .env .env.backup.$(date +%Y%m%d)

# 备份配置文件
cp .ralphconfig.json .ralphconfig.json.backup.$(date +%Y%m%d)

# 备份 Nginx 配置
cp /etc/nginx/sites-available/ralph /backup/nginx/ralph.$(date +%Y%m%d)
```

### Git 追踪配置

**初始化 Git 仓库：**

```bash
cd /opt/ralph-config
git init
git add .
git commit -m "Initial commit"

# 添加远程仓库
git remote add origin https://github.com/user01/ralph-config.git
git push -u origin main
```

**更新配置：**

```bash
cd /opt/ralph-config

# 复制新配置
cp /opt/ai-devops/.env .

# 提交变更
git add .
git commit -m "Update environment variables"
git push
```

---

## 日志备份

### 日志归档

**archive_logs.sh:**

```bash
#!/bin/bash
# archive_logs.sh

LOG_DIR="/var/log/ralph"
ARCHIVE_DIR="/backup/ralph/logs"
DATE=$(date +%Y%m%d)

# 创建归档目录
mkdir -p "$ARCHIVE_DIR"

# 归档日志文件
cd "$LOG_DIR"
tar -czf "$ARCHIVE_DIR/logs_$DATE.tar.gz" *.log

# 清理旧日志
find . -name "*.log" -mtime +30 -delete

echo "Logs archived: logs_$DATE.tar.gz"
```

**设置定时任务：**

```bash
# 每天凌晨 3 点归档日志
0 3 * * * /opt/ralph/scripts/archive_logs.sh >> /var/log/ralph/archive.log 2>&1
```

### 使用 logrotate

**配置文件：**

```bash
# /etc/logrotate.d/ralph
/var/log/ralph/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ralph ralph
    sharedscripts
    postrotate
        systemctl reload ralph-api > /dev/null 2>&1 || true
    endscript
}
```

---

## 恢复流程

### 恢复数据库

**从备份恢复：**

```bash
# 停止服务
systemctl stop ralph-api

# 备份当前数据库（以防万一）
cp agent_tasks.db agent_tasks.db.before_restore

# 恢复备份
sqlite3 agent_tasks.db < backup_20260414.sql

# 或从备份文件恢复
cp agent_tasks.db.backup.20260414 agent_tasks.db

# 验证数据库
sqlite3 agent_tasks.db "SELECT COUNT(*) FROM ralph_state;"

# 启动服务
systemctl start ralph-api

# 检查日志
journalctl -u ralph-api -f
```

### 恢复配置

```bash
# 从 Git 恢复
cd /opt/ralph-config
git pull

# 复制配置文件
cp .env /opt/ai-devops/
cp .ralphconfig.json /opt/ai-devops/

# 重新加载服务
systemctl reload ralph-api
```

### 恢复日志

```bash
# 解压日志备份
cd /var/log/ralph
tar -xzf /backup/ralph/logs/logs_20260414.tar.gz

# 查看日志
tail -f ralph.log
```

---

## 自动化备份

### 完整备份脚本

**full_backup.sh:**

```bash
#!/bin/bash
# full_backup.sh

set -e

BACKUP_ROOT="/backup/ralph"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$DATE"

# 创建备份目录
mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/db"
mkdir -p "$BACKUP_DIR/config"
mkdir -p "$BACKUP_DIR/logs"
mkdir -p "$BACKUP_DIR/code"

echo "Starting backup: $DATE"

# 备份数据库
echo "Backing up database..."
sqlite3 agent_tasks.db ".backup $BACKUP_DIR/db/ralph.db"
gzip -f "$BACKUP_DIR/db/ralph.db"

# 备份配置
echo "Backing up configuration..."
cp .env "$BACKUP_DIR/config/"
cp .ralphconfig.json "$BACKUP_DIR/config/"

# 备份日志
echo "Backing up logs..."
tar -czf "$BACKUP_DIR/logs/logs.tar.gz" /var/log/ralph/*.log

# 备份代码
echo "Backing up code..."
git rev-parse HEAD > "$BACKUP_DIR/code/git_commit.txt"

# 创建备份清单
echo "Backup completed at $(date)" > "$BACKUP_DIR/manifest.txt"
echo "Database: $BACKUP_DIR/db/ralph.db.gz" >> "$BACKUP_DIR/manifest.txt"
echo "Config: $BACKUP_DIR/config/" >> "$BACKUP_DIR/manifest.txt"
echo "Logs: $BACKUP_DIR/logs/logs.tar.gz" >> "$BACKUP_DIR/manifest.txt"
echo "Git commit: $(cat $BACKUP_DIR/code/git_commit.txt)" >> "$BACKUP_DIR/manifest.txt"

# 清理旧备份（保留 7 天）
find "$BACKUP_ROOT" -type d -mtime +7 -exec rm -rf {} +

echo "Backup completed successfully!"
```

**设置定时任务：**

```bash
# 每天凌晨 1 点完整备份
0 1 * * * /opt/ralph/scripts/full_backup.sh >> /var/log/ralph/backup.log 2>&1
```

---

### 云端备份

**上传到 S3:**

```bash
#!/bin/bash
# backup_to_s3.sh

BACKUP_DIR="/backup/ralph"
S3_BUCKET="s3://ralph-backups"
DATE=$(date +%Y%m%d)

# 上传最新备份
aws s3 sync "$BACKUP_DIR/$DATE" "$S3_BUCKET/$DATE"

# 设置生命周期策略（删除 30 天前的备份）
aws s3api put-bucket-lifecycle-configuration \
  --bucket ralph-backups \
  --lifecycle-configuration file://lifecycle.json
```

**lifecycle.json:**

```json
{
  "Rules": [
    {
      "ID": "DeleteOldBackups",
      "Status": "Enabled",
      "Filter": {
        "Prefix": ""
      },
      "Expiration": {
        "Days": 30
      }
    }
  ]
}
```

---

## 备份验证

### 验证脚本

**verify_backup.sh:**

```bash
#!/bin/bash
# verify_backup.sh

BACKUP_ROOT="/backup/ralph"
BACKUP_DIR="$1"

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 <backup_directory>"
    exit 1
fi

FULL_PATH="$BACKUP_ROOT/$BACKUP_DIR"

if [ ! -d "$FULL_PATH" ]; then
    echo "Backup directory not found: $FULL_PATH"
    exit 1
fi

echo "Verifying backup: $BACKUP_DIR"

# 验证数据库
echo "Checking database..."
if [ -f "$FULL_PATH/db/ralph.db.gz" ]; then
    echo "✓ Database file exists"
    gunzip -t "$FULL_PATH/db/ralph.db.gz" && echo "✓ Database file valid"
else
    echo "✗ Database file missing"
fi

# 验证配置
echo "Checking configuration..."
if [ -f "$FULL_PATH/config/.env" ]; then
    echo "✓ Environment file exists"
else
    echo "✗ Environment file missing"
fi

# 验证日志
echo "Checking logs..."
if [ -f "$FULL_PATH/logs/logs.tar.gz" ]; then
    echo "✓ Log archive exists"
    tar -tzf "$FULL_PATH/logs/logs.tar.gz" > /dev/null 2>&1 && echo "✓ Log archive valid"
else
    echo "✗ Log archive missing"
fi

echo "Verification completed"
```

**使用：**

```bash
./verify_backup.sh 20260414_010000
```

---

## 灾难恢复

### 完整系统恢复

**restore.sh:**

```bash
#!/bin/bash
# restore.sh

BACKUP_DIR="$1"

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 <backup_directory>"
    exit 1
fi

echo "Restoring from backup: $BACKUP_DIR"

# 停止服务
systemctl stop ralph-api

# 备份当前状态
mkdir -p /tmp/before_restore
cp -r /opt/ai-devops /tmp/before_restore/

# 恢复数据库
echo "Restoring database..."
rm -f agent_tasks.db
gunzip -c "$BACKUP_DIR/db/ralph.db.gz" > agent_tasks.db

# 恢复配置
echo "Restoring configuration..."
cp "$BACKUP_DIR/config/.env" ./
cp "$BACKUP_DIR/config/.ralphconfig.json" ./

# 恢复日志
echo "Restoring logs..."
tar -xzf "$BACKUP_DIR/logs/logs.tar.gz" -C /var/log/ralph/

# 启动服务
systemctl start ralph-api

# 验证恢复
echo "Verifying restoration..."
sqlite3 agent_tasks.db "SELECT COUNT(*) FROM ralph_state;"

echo "Restoration completed!"
```

---

## 最佳实践

1. **定期备份**: 至少每天一次完整备份
2. **多地存储**: 本地 + 云端
3. **加密备份**: 使用加密保护敏感数据
4. **测试恢复**: 定期测试恢复流程
5. **监控备份**: 监控备份任务是否成功
6. **版本化配置**: 使用 Git 管理配置
7. **文档记录**: 记录恢复流程

---

## 参考文档

- [部署指南](./deployment.md)
- [配置参考](./configuration.md)
- [监控指南](./monitoring.md)
