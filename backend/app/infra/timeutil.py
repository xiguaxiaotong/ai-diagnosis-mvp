"""时间工具（W9：pytest warnings 清零附带收编）。

datetime.utcnow() 自 Py3.12 起废弃（DeprecationWarning）；但本项目 DB 的
DateTime 列全部是 naive UTC 口径（SQLite 无 tz 列，存量数据不带时区），
直接改 datetime.now(UTC) 会引入 aware 对象（sqlite3 会存成带 +00:00 的
ISO 串，与存量数据比较/解析不兼容）。这里取 aware 再剥 tzinfo，
与 utcnow() 语义完全等价、存储格式零变化。
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """当前 UTC 时间（naive datetime），替代废弃的 datetime.utcnow()。"""
    return datetime.now(UTC).replace(tzinfo=None)
