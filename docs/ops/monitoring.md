# 监控指南

## 概述

本文档提供 Ralph 集成系统的监控指南，包括日志、指标收集和告警配置。

---

## 目录

- [日志监控](#日志监控)
- [指标监控](#指标监控)
- [告警配置](#告警配置)
- [性能监控](#性能监控)
- [健康检查](#健康检查)

---

## 日志监控

### 日志级别

| 级别 | 说明 | 使用场景 |
|------|------|----------|
| `DEBUG` | 详细调试信息 | 开发和问题排查 |
| `INFO` | 一般信息 | 正常运行日志 |
| `WARNING` | 警告信息 | 潜在问题 |
| `ERROR` | 错误信息 | 需要关注 |
| `CRITICAL` | 严重错误 | 立即处理 |

### 日志格式

标准日志格式：

```
[2026-04-14T15:30:00Z] INFO [task_to_prd] Converting task_spec.json to prd.json
[2026-04-14T15:30:05Z] DEBUG [ralph_runner] Starting Ralph execution
[2026-04-14T15:35:00Z] WARNING [quality_gate] Test failed: 3 assertions failed
[2026-04-14T15:40:00Z] ERROR [ralph_runner] Execution timeout after 7200s
[2026-04-14T15:40:00Z] CRITICAL [main] System panic: Out of memory
```

### 日志文件位置

| 日志类型 | 路径 | 说明 |
|----------|------|------|
| **应用日志** | `/var/log/ralph/ralph.log` | 主应用日志 |
| **API 日志** | `/var/log/ralph/api.log` | API 请求日志 |
| **任务日志** | `/var/log/ralph/tasks/` | 各任务日志 |
| **错误日志** | `/var/log/ralph/error.log` | 错误汇总 |

### 日志轮转配置

**logrotate 配置：**

```bash
# /etc/logrotate.d/ralph
/var/log/ralph/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ralph ralph
    sharedscripts
    postrotate
        systemctl reload ralph-api
    endscript
}
```

### 日志查询

**使用 grep:**

```bash
# 查询特定任务的日志
grep "task-20260414-001" /var/log/ralph/ralph.log

# 查询错误日志
grep -i error /var/log/ralph/ralph.log

# 查询最近 1 小时的日志
find /var/log/ralph/ -name "*.log" -mmin -60 -exec tail -f {} +
```

**使用 journalctl（Systemd 服务）：**

```bash
# 查看实时日志
journalctl -u ralph-api -f

# 查看最近 100 行
journalctl -u ralph-api -n 100

# 按时间过滤
journalctl -u ralph-api --since "1 hour ago"
```

### ELK Stack 集成

**Filebeat 配置：**

```yaml
# filebeat.yml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/ralph/*.log
    fields:
      service: ralph
      environment: production
    fields_under_root: true

output.elasticsearch:
  hosts: ["localhost:9200"]
  index: "ralph-%{+yyyy.MM.dd}"

setup.template.settings:
  index.number_of_shards: 1
  index.number_of_replicas: 1
```

---

## 指标监控

### Prometheus 指标

**内置指标：**

| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `ralph_tasks_total` | Counter | 总任务数 |
| `ralph_tasks_completed_total` | Counter | 完成的任务数 |
| `ralph_tasks_failed_total` | Counter | 失败的任务数 |
| `ralph_task_duration_seconds` | Histogram | 任务执行时间 |
| `ralph_iterations_total` | Counter | 总迭代次数 |
| `ralph_api_requests_total` | Counter | API 请求总数 |
| `ralph_api_request_duration_seconds` | Histogram | API 请求耗时 |
| `ralph_active_tasks` | Gauge | 当前运行任务数 |

**自定义指标：**

```python
from prometheus_client import Counter, Histogram, Gauge

# 定义指标
tasks_total = Counter('ralph_tasks_total', 'Total number of tasks')
tasks_completed = Counter('ralph_tasks_completed_total', 'Total completed tasks')
tasks_failed = Counter('ralph_tasks_failed_total', 'Total failed tasks')
task_duration = Histogram('ralph_task_duration_seconds', 'Task duration')
active_tasks = Gauge('ralph_active_tasks', 'Active tasks')

# 使用指标
tasks_total.inc()
task_duration.observe(3600)
active_tasks.set(5)
```

### Prometheus 配置

**scrape 配置：**

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'ralph'
    static_configs:
      - targets: ['localhost:9090']
        labels:
          service: 'ralph'
          environment: 'production'

  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']
```

### Grafana Dashboard

**常用面板：**

1. **任务概览**
   - 总任务数
   - 完成率
   - 失败率
   - 平均执行时间

2. **任务趋势**
   - 每小时任务数
   - 完成率趋势
   - 失败率趋势

3. **性能指标**
   - 任务执行时间分布
   - API 请求延迟
   - 资源使用率

4. **系统健康**
   - 活跃任务数
   - 错误率
   - 系统负载

**示例查询：**

```promql
# 任务完成率
rate(ralph_tasks_completed_total[1h]) / rate(ralph_tasks_total[1h])

# 平均执行时间
rate(ralph_task_duration_seconds_sum[5m]) / rate(ralph_task_duration_seconds_count[5m])

# P95 执行时间
histogram_quantile(0.95, ralph_task_duration_seconds_bucket)

# 错误率
rate(ralph_tasks_failed_total[1h]) / rate(ralph_tasks_total[1h])
```

---

## 告警配置

### Alertmanager 配置

**告警路由：**

```yaml
# alertmanager.yml
route:
  receiver: 'default'
  group_by: ['alertname', 'service']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h

receivers:
  - name: 'default'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK}'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
    telegram_configs:
      - bot_token: '${TELEGRAM_BOT_TOKEN}'
        chat_id: '${TELEGRAM_CHAT_ID}'
        parse_mode: 'HTML'
        message: |
          <b>{{ .GroupLabels.alertname }}</b>
          {{ range .Alerts }}
          {{ .Annotations.description }}
          {{ end }}
```

### 告警规则

**任务告警：**

```yaml
# alerts.yml
groups:
  - name: ralph_tasks
    interval: 30s
    rules:
      - alert: TaskTimeout
        expr: ralph_task_duration_seconds > 7200
        for: 5m
        labels:
          severity: critical
          service: ralph
        annotations:
          summary: "Task {{ $labels.task_id }} has timed out"
          description: "Task {{ $labels.task_id }} has been running for more than 2 hours"

      - alert: HighFailureRate
        expr: rate(ralph_tasks_failed_total[1h]) > 0.1
        for: 10m
        labels:
          severity: warning
          service: ralph
        annotations:
          summary: "High task failure rate detected"
          description: "Failure rate is {{ $value | humanizePercentage }}"

      - alert: TaskStalled
        expr: ralph_task_duration_seconds > 1800 and ralph_task_progress < 50
        for: 30m
        labels:
          severity: warning
          service: ralph
        annotations:
          summary: "Task {{ $labels.task_id }} appears stalled"
          description: "Task has not progressed beyond 50% in 30 minutes"

      - alert: NoNewTasks
        expr: rate(ralph_tasks_total[1h]) == 0
        for: 2h
        labels:
          severity: info
          service: ralph
        annotations:
          summary: "No new tasks in the last 2 hours"
          description: "This may indicate a problem with the task queue"
```

**API 告警：**

```yaml
  - name: ralph_api
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(ralph_api_requests_total{status=~"5.."}[5m]) / rate(ralph_api_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
          service: ralph-api
        annotations:
          summary: "High API error rate"
          description: "Error rate is {{ $value | humanizePercentage }}"

      - alert: HighLatency
        expr: histogram_quantile(0.95, ralph_api_request_duration_seconds) > 5
        for: 5m
        labels:
          severity: warning
          service: ralph-api
        annotations:
          summary: "High API latency"
          description: "P95 latency is {{ $value }}s"

      - alert: ServiceDown
        expr: up{job="ralph"} == 0
        for: 1m
        labels:
          severity: critical
          service: ralph
        annotations:
          summary: "Ralph service is down"
          description: "The Ralph service has been down for more than 1 minute"
```

---

## 性能监控

### 系统监控

**CPU 监控：**

```bash
# CPU 使用率
top -bn1 | grep "Cpu(s)" | awk '{print $2}'

# CPU 核心使用
mpstat -P ALL 1
```

**内存监控：**

```bash
# 内存使用情况
free -h

# 内存使用率
free | awk '/Mem:/ {printf("%.2f\n", $3/$2 * 100)}'
```

**磁盘监控：**

```bash
# 磁盘使用情况
df -h

# 磁盘 I/O
iostat -x 1
```

### 应用性能

**Python Profiling：**

```python
import cProfile
import pstats

def profile_function():
    pr = cProfile.Profile()
    pr.enable()
    # 运行代码
    pr.disable()
    stats = pstats.Stats(pr)
    stats.sort_stats('cumulative')
    stats.print_stats(10)

profile_function()
```

**内存分析：**

```bash
# 使用 memory_profiler
python -m memory_profiler script.py

# 使用 objgraph
python -c "import objgraph; objgraph.show_most_common_types()"
```

---

## 健康检查

### 健康检查端点

```python
from fastapi import FastAPI
import psutil
import sqlite3

app = FastAPI()

@app.get("/health")
async def health_check():
    """健康检查端点"""
    checks = {
        "status": "healthy",
        "checks": {}
    }

    # 检查数据库连接
    try:
        conn = sqlite3.connect("agent_tasks.db")
        conn.execute("SELECT 1")
        conn.close()
        checks["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        checks["status"] = "unhealthy"
        checks["checks"]["database"] = {"status": "unhealthy", "error": str(e)}

    # 检查磁盘空间
    disk = psutil.disk_usage('/')
    if disk.percent > 90:
        checks["status"] = "unhealthy"
        checks["checks"]["disk"] = {"status": "unhealthy", "usage": disk.percent}
    else:
        checks["checks"]["disk"] = {"status": "healthy", "usage": disk.percent}

    # 检查内存
    mem = psutil.virtual_memory()
    if mem.percent > 90:
        checks["status"] = "degraded"
        checks["checks"]["memory"] = {"status": "degraded", "usage": mem.percent}
    else:
        checks["checks"]["memory"] = {"status": "healthy", "usage": mem.percent}

    # 检查 CPU
    cpu = psutil.cpu_percent(interval=1)
    if cpu > 90:
        checks["status"] = "degraded"
        checks["checks"]["cpu"] = {"status": "degraded", "usage": cpu}
    else:
        checks["checks"]["cpu"] = {"status": "healthy", "usage": cpu}

    # 根据检查结果返回状态码
    status_code = 200 if checks["status"] == "healthy" else 503

    return checks, status_code
```

### 监控脚本

**定期检查脚本：**

```bash
#!/bin/bash
# monitor.sh

# 健康检查
HEALTH=$(curl -s http://localhost:8000/health | jq -r '.status')

if [ "$HEALTH" != "healthy" ]; then
    echo "Health check failed: $HEALTH"
    # 发送告警
    curl -X POST $SLACK_WEBHOOK -d "{\"text\": \"⚠️ Ralph service is $HEALTH\"}"
fi

# 检查磁盘空间
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "Disk usage is critical: $DISK_USAGE%"
    # 发送告警
    curl -X POST $SLACK_WEBHOOK -d "{\"text\": \"🚨 Disk usage is critical: $DISK_USAGE%\"}"
fi

# 检查内存
MEM_USAGE=$(free | awk '/Mem:/ {printf("%.0f", $3/$2 * 100)}')
if [ "$MEM_USAGE" -gt 90 ]; then
    echo "Memory usage is critical: $MEM_USAGE%"
    # 发送告警
    curl -X POST $SLACK_WEBHOOK -d "{\"text\": \"🚨 Memory usage is critical: $MEM_USAGE%\"}"
fi
```

**设置 Cron 定时任务：**

```bash
# 每 5 分钟检查一次
*/5 * * * * /opt/ai-devops/scripts/monitor.sh >> /var/log/ralph/monitor.log 2>&1
```

---

## 最佳实践

1. **分层监控**：应用层、服务层、基础设施层
2. **可视化**：使用 Grafana 仪表板展示关键指标
3. **告警分级**：区分 Critical、Warning、Info
4. **告警去重**：避免重复告警
5. **日志聚合**：使用 ELK 或类似工具
6. **定期审查**：定期审查和优化监控规则
7. **文档记录**：记录所有告警的处理流程

---

## 参考文档

- [配置参考](./configuration.md)
- [故障排查](./troubleshooting.md)
- [部署指南](./deployment.md)
