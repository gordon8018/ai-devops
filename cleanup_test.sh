#!/bin/bash
# 清理测试数据脚本

echo "清理完整生产工作流测试数据..."

# 选项 1: 保留演示内容（推荐）
# 只删除临时文件，保留 prd.json 和 TaskSpec

# 选项 2: 完全清理
# 删除所有测试相关文件

# 清理临时测试文件
rm -f /home/user01/ai-devops/test_full_pipeline.py
rm -f /home/user01/ai-devops/TEST_PRODUCTION_WORKFLOW_REPORT.md
rm -f /tmp/api_server.log
rm -f /tmp/api_server2.log

# 询问是否保留 prd.json 和 TaskSpec
echo ""
echo "清理完成！"
echo "保留的文件（用于演示）:"
echo "  - test_production_task.json (TaskSpec 模板)"
echo "  - .clawdbot/ralph_test/prd.json (转换结果)"
echo "  - TEST_PRODUCTION_WORKFLOW_DETAILED_REPORT.md (详细报告)"
echo ""
echo "如需完全清理，请手动删除上述文件"
