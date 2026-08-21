#!/usr/bin/env python3
"""Alpha Factory 一键数据库初始化与表结构校验脚本.

使用方法:
    python init_db.py          # 默认初始化或增量升级 data/alpha_research.db
    python init_db.py --verify # 校验当前数据库完整性与版本
    python init_db.py --reset  # 清空并全新初始化数据库
"""

from alpha_operator_framework.database.init_db import main

if __name__ == "__main__":
    main()
