# 质量门禁设计

## 概述

质量门禁（Quality Gate）是 Ralph 集成系统的关键质量控制组件，确保生成的代码通过所有质量检查后才能进入下一阶段（创建 PR、合并代码）。

---

## 1. 质量门禁架构

### 1.1 整体流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    Quality Gate Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Code Review │  │   CI/CD      │  │   Security   │         │
│  │   检查       │  │   检查       │  │   扫描       │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │  通过    │◀────▶│  通过    │◀────▶│  通过    │
    │  拒绝    │      │  拒绝    │      │  拒绝    │
    └──────────┘      └──────────┘      └──────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  质量门禁    │
                    │  判定逻辑    │
                    └──────┬───────┘
                           │
            ┌──────────────┴──────────────┐
            │                             │
            ▼                             ▼
      ┌──────────┐                  ┌──────────┐
      │  允许通过 │                  │  阻止推进 │
      │  创建 PR │                  │  需要修复 │
      └──────────┘                  └──────────┘
```

### 1.2 质量检查层级

| 层级 | 检查项 | 时机 | 阻塞性 |
|------|--------|------|--------|
| **L1: 本地检查** | Typecheck, Lint, Test | 每次迭代后 | 阻塞（必须通过） |
| **L2: Code Review** | 人工审核 | 创建 PR 后 | 阻塞（必须批准） |
| **L3: CI/CD** | 自动化测试、构建 | PR 提交后 | 阻塞（必须通过） |
| **L4: 安全扫描** | SAST, DAST | 可配置 | 可配置（建议阻塞） |

---

## 2. 质量检查配置

### 2.1 prd.json 中的质量配置

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false,
    "securityScan": {
      "enabled": true,
      "tools": ["snyk", "trivy"],
      "blocking": true
    },
    "codeReview": {
      "required": true,
      "minReviewers": 1,
      "autoAssign": ["@reviewer1", "@reviewer2"]
    }
  }
}
```

### 2.2 质量检查脚本

#### Typecheck

```bash
# TypeScript
bun run typecheck
# 或
npx tsc --noEmit

# Python
mypy src/
```

#### Lint

```bash
# ESLint
bun run lint

# Pylint
pylint src/

# RuboCop
rubocop
```

#### Test

```bash
# 单元测试
bun run test

# 带覆盖率
bun run test:coverage

# 集成测试
bun run test:integration
```

#### 安全扫描

```bash
# Snyk (依赖漏洞)
snyk test

# Trivy (镜像扫描)
trivy image myapp:latest

# Bandit (Python 安全)
bandit -r src/
```

---

## 3. Code Review 集成

### 3.1 创建 PR 时自动分配 Reviewer

```python
import requests
from github import Github

def create_pr_with_reviewers(
    repo: str,
    branch: str,
    title: str,
    reviewers: list[str]
):
    """创建 PR 并自动分配 Reviewer"""

    g = Github(token=os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(repo)

    pr = repo.create_pull(
        title=title,
        body=f"Automated PR from Ralph task",
        head=branch,
        base="main"
    )

    # 分配 Reviewer
    pr.create_review_request(reviewers=reviewers)

    return pr
```

### 3.2 监控 Review 状态

```python
def get_review_status(pr):
    """获取 Review 状态"""
    reviews = pr.get_reviews()

    status = {
        "approved": 0,
        "requested_changes": 0,
        "commented": 0,
        "pending": 0
    }

    for review in reviews:
        if review.state == "APPROVED":
            status["approved"] += 1
        elif review.state == "CHANGES_REQUESTED":
            status["requested_changes"] += 1
        elif review.state == "COMMENTED":
            status["commented"] += 1

    # 计算待决的 review requests
    requested_reviewers = pr.get_review_requests()
    status["pending"] = len(list(requested_reviewers[0]))  # [0] = reviewers

    return status

def is_review_approved(pr, min_reviewers=1):
    """检查是否已批准"""
    status = get_review_status(pr)
    return (
        status["approved"] >= min_reviewers and
        status["requested_changes"] == 0
    )
```

### 3.3 处理 Review 评论

```python
def handle_review_comments(pr):
    """处理 Review 评论，生成修复建议"""
    reviews = pr.get_reviews()

    for review in reviews:
        if review.state == "CHANGES_REQUESTED":
            # 收集评论
            comments = review.get_comments()
            suggestions = []

            for comment in comments:
                suggestions.append({
                    "file": comment.path,
                    "line": comment.position,
                    "comment": comment.body
                })

            # 返回给 Ralph 进行修复
            return suggestions

    return []
```

---

## 4. CI/CD 监控

### 4.1 GitHub Actions 监控

```python
def get_ci_status(pr):
    """获取 PR 的 CI 状态"""
    runs = pr.get_commits().reversed[0].get_statuses()

    status = {
        "pending": 0,
        "success": 0,
        "failure": 0,
        "total": 0
    }

    for run in runs:
        status["total"] += 1
        if run.state == "pending":
            status["pending"] += 1
        elif run.state == "success":
            status["success"] += 1
        elif run.state == "failure" or run.state == "error":
            status["failure"] += 1

    return status

def is_ci_passed(pr):
    """检查 CI 是否通过"""
    status = get_ci_status(pr)
    return (
        status["total"] > 0 and
        status["failure"] == 0 and
        status["pending"] == 0
    )
```

### 4.2 CI 检查配置

```yaml
# .github/workflows/ralph-quality.yml
name: Ralph Quality Gate

on:
  pull_request:
    branches: [main]

jobs:
  quality-check:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Setup Bun
        uses: oven-sh/setup-bun@v1
        with:
          bun-version: latest

      - name: Install dependencies
        run: bun install

      - name: Typecheck
        run: bun run typecheck

      - name: Lint
        run: bun run lint

      - name: Test
        run: bun run test --coverage

      - name: Upload coverage
        uses: codecov/codecov-action@v3

      - name: Security scan
        run: npx snyk test

      - name: Build
        run: bun run build
```

### 4.3 CI 状态同步

```python
def sync_ci_status_to_ralph_state(pr, ralph_state, task_id):
    """同步 CI 状态到 Ralph 状态存储"""
    ci_status = get_ci_status(pr)

    if ci_status["pending"] > 0:
        ralph_state.update(task_id, status="ci_pending")
    elif ci_status["failure"] > 0:
        ralph_state.update(task_id, status="ci_failed")
        ralph_state.append_log(task_id, "CI checks failed")
    elif ci_status["total"] > 0 and ci_status["failure"] == 0:
        ralph_state.update(task_id, status="ci_passed")
        ralph_state.append_log(task_id, "CI checks passed")
```

---

## 5. Python API

### 5.1 质量门禁管理器

```python
from quality_gate import QualityGateManager

# 初始化
qg = QualityGateManager(
    github_token=os.getenv("GITHUB_TOKEN"),
    repo="user01/ai-devops"
)

# 运行本地质量检查
result = qg.run_local_checks(
    branch="ralph/task-001",
    checks=["typecheck", "lint", "test"]
)
# Returns: {
#     "typecheck": {"status": "passed", "duration": 5.2},
#     "lint": {"status": "passed", "duration": 3.1},
#     "test": {"status": "failed", "errors": [...]}
# }

# 创建 PR
pr = qg.create_pr(
    branch="ralph/task-001",
    title="Add priority field",
    reviewers=["@gordon"]
)

# 监控质量门禁
while True:
    status = qg.get_quality_gate_status(pr.number)

    if status["all_passed"]:
        print("Quality gate passed!")
        break
    elif status["blocking_issues"]:
        print(f"Blocking issues: {status['blocking_issues']}")
        break

    time.sleep(30)
```

### 5.2 质量门禁状态

```python
status = qg.get_quality_gate_status(pr_number)

# 返回格式
{
    "local_checks": {
        "typecheck": {"status": "passed"},
        "lint": {"status": "passed"},
        "test": {"status": "passed"}
    },
    "ci_checks": {
        "build": {"status": "passed"},
        "test": {"status": "passed"},
        "security": {"status": "passed"}
    },
    "code_review": {
        "status": "approved",
        "approved_by": ["@gordon"],
        "pending": 0
    },
    "all_passed": true,
    "blocking_issues": []
}
```

---

## 6. 质量门禁策略

### 6.1 严格模式

```python
qg = QualityGateManager(
    github_token=token,
    repo="user01/ai-devops",
    policy="strict"  # 所有检查都必须通过
)
```

### 6.2 宽松模式

```python
qg = QualityGateManager(
    github_token=token,
    repo="user01/ai-devops",
    policy="lenient"  # 允许非阻塞警告
)
```

### 6.3 自定义策略

```python
custom_policy = {
    "blocking_checks": ["typecheck", "test"],
    "warning_checks": ["lint", "security"],
    "min_reviewers": 1,
    "ci_timeout": 3600
}

qg = QualityGateManager(
    github_token=token,
    repo="user01/ai-devops",
    policy=custom_policy
)
```

---

## 7. CLI 工具

### 7.1 命令行接口

```bash
# 运行本地检查
./quality_gate.py check <branch> [--checks typecheck,lint,test]
./quality_gate.py check ralph/task-001 --checks all

# 创建 PR
./quality_gate.py create-pr <branch> --title "Title" --reviewers @user1,@user2

# 检查 PR 状态
./quality_gate.py status <pr_number>

# 监控 PR
./quality_gate.py watch <pr_number> --interval 30

# 强制通过（谨慎使用）
./quality_gate.py approve <pr_number> --reason "Manual override"
```

---

## 8. 错误处理

### 8.1 质量检查失败处理

```python
result = qg.run_local_checks(branch="ralph/task-001")

if result["failed"]:
    # 生成修复建议
    suggestions = qg.generate_fix_suggestions(result)

    # 返回给 Ralph
    return {
        "status": "failed",
        "errors": result["errors"],
        "suggestions": suggestions
    }
```

### 8.2 CI 失败处理

```python
ci_status = get_ci_status(pr)

if ci_status["failure"] > 0:
    # 获取失败日志
    failed_runs = get_failed_ci_runs(pr)

    # 分析失败原因
    root_cause = analyze_ci_failure(failed_runs)

    # 返回给 Ralph
    return {
        "status": "ci_failed",
        "failed_checks": failed_runs,
        "root_cause": root_cause
    }
```

---

## 9. 最佳实践

1. **分层检查**: L1 本地检查必须快速，L2/L3 可以更全面
2. **自动化优先**: 尽量减少人工干预，提高效率
3. **合理超时**: CI 检查设置合理超时，避免无限等待
4. **详细日志**: 记录所有质量检查结果，便于追溯
5. **渐进式增强**: 从简单检查开始，逐步增加复杂度
6. **定期更新**: 及时更新检查规则和工具版本
7. **性能监控**: 监控质量检查耗时，优化慢速检查

---

## 10. 扩展性

### 10.1 自定义检查

```python
class CustomCheck(BaseCheck):
    def run(self):
        # 自定义检查逻辑
        result = subprocess.run(
            ["custom-tool", "check"],
            capture_output=True
        )

        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "output": result.stdout.decode(),
            "errors": result.stderr.decode()
        }

qg.register_check("custom", CustomCheck())
```

### 10.2 集成其他工具

```python
# SonarQube 集成
qg.integrate_sonarqube(
    url="https://sonarqube.example.com",
    token="sonar-token",
    quality_gate="SonarQube Quality Gate"
)

# Codecov 集成
qg.integrate_codecov(
    token="codecov-token",
    min_coverage=80
)

# OWASP ZAP 集成
qg.integrate_zap(
    scan_url="https://staging.example.com",
    min_severity="medium"
)
```

---

## 11. 参考文档

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [Codecov 文档](https://docs.codecov.com)
- [Snyk 文档](https://docs.snyk.io)
- [完整集成文档](../RALPH_INTEGRATION.md)
