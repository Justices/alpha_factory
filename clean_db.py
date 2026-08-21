#!/usr/bin/env python3
"""Alpha Factory 一键数据库清理与维护脚本.

使用方法:
    python clean_db.py                  # 清理失败/异常任务并释放磁盘空间 (默认)
    python clean_db.py --mode stale     # 清理失败项、剪枝项与孤儿数据
    python clean_db.py --mode all_data  # 清空所有历史回测数据 (保留表结构与模板库)
    python clean_db.py --dry-run        # 仅预览预计清理条数，不实际删除
"""

from alpha_operator_framework.database.cleaner import main

if __name__ == "__main__":
    main()
