"""
Run history 读取服务。

模块职责：
1. 读取 runtime 写入的 `debug_data/runs/index.json` 轻量索引。
2. 根据 run_id 读取对应 run 的 summary 与 report artifact。
3. 为 CLI 查询最近运行记录提供稳定、低复杂度的数据访问接口。

设计目标：
1. 复用已有文件型 run history，不引入数据库或后台服务。
2. 将文件读取、缺失处理和路径拼接集中在服务层。
3. 让 main.py 只负责 CLI 参数分流和展示调用。

当前限制：
- 当前只读取本地 artifact 文件，不做跨机器同步或远程查询。
- 当前不会自动修复损坏的 history 文件，只返回空结果或空文本。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class RunHistory:
    """
    本地文件型 run history 读取器。

    职责边界：
    - 只读取 runtime 已保存的 index、summary 和 report。
    - 不修改 index，不删除历史记录，不生成新的 run。
    """

    def __init__(self, artifact_dir: str | Path = "debug_data"):
        """
        初始化 history 读取器。

        参数：
        - artifact_dir: runtime artifact 根目录，默认与 ResearchRuntime 保持一致。
        """
        self.artifact_dir = Path(artifact_dir)
        self.runs_dir = self.artifact_dir / "runs"

    def list_runs(self) -> List[Dict[str, Any]]:
        """
        读取 runs/index.json 中的轻量运行记录。

        输出：
        - 按 runtime 写入顺序排列的 run 记录列表。
        - 文件不存在、格式错误或解析失败时返回空列表。
        """
        records = self._load_json(self.runs_dir / "index.json", default=[])
        if not isinstance(records, list):
            return []

        return [
            item
            for item in records
            if isinstance(item, dict) and item.get("run_id")
        ]

    def latest_run_id(self) -> Optional[str]:
        """
        返回最近一次 run_id。
        """
        records = self.list_runs()
        if not records:
            return None

        return records[0].get("run_id")

    def load_summary(self, run_id: str) -> Dict[str, Any]:
        """
        读取指定 run 的 summary.json。

        输入：
        - run_id: 运行编号。

        输出：
        - summary 字典；文件缺失或解析失败时返回空字典。
        """
        if not run_id:
            return {}

        summary = self._load_json(self.runs_dir / run_id / "summary.json", default={})
        return summary if isinstance(summary, dict) else {}

    def load_report(self, run_id: str) -> str:
        """
        读取指定 run 的 report.md。
        """
        if not run_id:
            return ""

        return self._load_text(self.runs_dir / run_id / "report.md")

    def load_run(self, run_id: str) -> Dict[str, Any]:
        """
        读取指定 run 的 summary 与 report。

        输出：
        - run_id: 运行编号
        - summary: summary.json 内容
        - report: report.md 内容
        - found: 是否至少读取到 summary 或 report
        """
        summary = self.load_summary(run_id)
        report = self.load_report(run_id)

        return {
            "run_id": run_id,
            "summary": summary,
            "report": report,
            "found": bool(summary or report),
        }

    def load_latest_run(self) -> Dict[str, Any]:
        """
        读取最近一次 run 的 summary 与 report。
        """
        run_id = self.latest_run_id()
        if not run_id:
            return {
                "run_id": "",
                "summary": {},
                "report": "",
                "found": False,
            }

        return self.load_run(run_id)

    def _load_json(self, path: Path, default: Any) -> Any:
        """
        读取 JSON 文件，失败时返回 default。
        """
        if not path.exists():
            return default

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _load_text(self, path: Path) -> str:
        """
        读取 UTF-8 文本文件，失败时返回空字符串。
        """
        if not path.exists():
            return ""

        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
