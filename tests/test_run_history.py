"""
Run history 读取服务回归测试。

这些测试保护本地 run history 查询能力：
- index.json 应能被读取为最近运行列表
- latest run 应来自 index 第一条记录
- 指定 run 应能读取 summary 与 report
- 缺失或损坏文件应返回稳定空结果

说明：
- 测试使用内存替身，避免 Windows sandbox 下临时目录权限影响测试稳定性。
"""

import unittest
from pathlib import Path

from services.run_history import RunHistory


class MemoryRunHistory(RunHistory):
    """
    使用内存字典模拟 artifact 文件读取。
    """

    def __init__(self, files):
        super().__init__(artifact_dir="debug_data")
        self.files = files

    def _load_json(self, path: Path, default):
        value = self.files.get(path.as_posix())
        if isinstance(value, Exception):
            return default
        return value if value is not None else default

    def _load_text(self, path: Path) -> str:
        value = self.files.get(path.as_posix())
        if isinstance(value, str):
            return value
        return ""


class RunHistoryTests(unittest.TestCase):
    def test_list_runs_reads_index_records(self):
        history = MemoryRunHistory({
            "debug_data/runs/index.json": [
                {
                    "run_id": "run-2",
                    "question": "第二个问题",
                },
                {
                    "run_id": "run-1",
                    "question": "第一个问题",
                },
            ],
        })

        records = history.list_runs()

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["run_id"], "run-2")

    def test_latest_run_id_uses_first_index_record(self):
        history = MemoryRunHistory({
            "debug_data/runs/index.json": [
                {"run_id": "run-latest"},
                {"run_id": "run-old"},
            ],
        })

        self.assertEqual(history.latest_run_id(), "run-latest")

    def test_load_run_reads_summary_and_report(self):
        history = MemoryRunHistory({
            "debug_data/runs/run-test/summary.json": {
                "run_id": "run-test",
                "status": "completed",
                "report_validation_valid": True,
            },
            "debug_data/runs/run-test/report.md": "# 报告",
        })

        result = history.load_run("run-test")

        self.assertTrue(result["found"])
        self.assertEqual(result["summary"]["run_id"], "run-test")
        self.assertEqual(result["report"], "# 报告")

    def test_missing_history_returns_empty_results(self):
        history = MemoryRunHistory({})

        self.assertEqual(history.list_runs(), [])
        self.assertIsNone(history.latest_run_id())
        self.assertFalse(history.load_latest_run()["found"])
        self.assertFalse(history.load_run("missing")["found"])

    def test_invalid_index_returns_empty_list(self):
        history = MemoryRunHistory({
            "debug_data/runs/index.json": {"unexpected": "shape"},
        })

        self.assertEqual(history.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
