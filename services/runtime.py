"""
Research workflow 运行时模块。

模块职责：
1. 统一执行 workflow 节点并合并节点输出
2. 记录每个节点的运行状态、关键数量指标和错误信息
3. 生成单次 research run 的结构化摘要
4. 保存 full v2 debug 所需的运行产物

设计目标：
1. 将 debug_run.py 中的运行控制逻辑下沉为可复用服务
2. 保持 runtime 层轻量，只负责“如何运行与记录”，不改变节点业务逻辑
3. 为后续展示运行轨迹、失败复盘和历史 run 管理提供基础结构

当前限制：
- 当前 runtime 仍是同步、单进程执行器
- 当前 artifact 保存使用 debug_data/latest_* 与 debug_data/runs/{run_id}/ 双写
- 当前不会自动恢复失败 run，仅记录失败节点并重新抛出异常
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


NodeFunc = Callable[[Dict[str, Any]], Dict[str, Any]]
RUN_HISTORY_LIMIT = 20


def _utc_now_iso() -> str:
    """
    返回 UTC ISO 时间字符串。

    设计原因：
    - run_id 与 step 时间戳应稳定、可排序
    - 使用 UTC 可避免本地时区差异影响后续复盘
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_run_id() -> str:
    """
    构造本地调试 run 的默认编号。
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}"


def _count_successful_page_reads(page_results: List[Dict[str, Any]]) -> int:
    """
    统计成功读取正文的页面数量。
    """
    return sum(1 for item in page_results if item.get("read_success", False))


def _count_fallback_page_reads(page_results: List[Dict[str, Any]]) -> int:
    """
    统计使用 fallback 内容的页面数量。
    """
    return sum(1 for item in page_results if not item.get("read_success", False))


class ResearchRuntime:
    """
    Deep Research Agent v2 的轻量运行控制与观测层。

    职责边界：
    - 负责执行节点、合并 state、记录 trace、保存 artifacts
    - 不负责搜索、页面读取、证据构建、报告生成等业务策略
    - 不替代 graph，只为本地 debug 和后续工程化展示提供统一运行骨架
    """

    def __init__(
        self,
        question: str,
        artifact_dir: str | Path = "debug_data",
        run_id: Optional[str] = None,
    ):
        """
        初始化一次 research run。

        参数：
        - question: 原始研究问题
        - artifact_dir: 调试产物保存目录
        - run_id: 可选运行编号，测试或复盘时可传入固定值
        """
        self.question = question
        self.run_id = run_id or _build_run_id()
        self.started_at = _utc_now_iso()
        self.ended_at: Optional[str] = None
        self.status = "running"
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(exist_ok=True)

    def initial_state(self) -> Dict[str, Any]:
        """
        构造 workflow 的初始 state。

        输出：
        - question: 原始研究问题
        - run_id: 当前运行编号
        - debug_trace: 节点级运行轨迹
        """
        return {
            "question": self.question,
            "run_id": self.run_id,
            "debug_trace": [],
        }

    def run_step(
        self,
        state: Dict[str, Any],
        step_name: str,
        node_func: NodeFunc,
    ) -> Dict[str, Any]:
        """
        执行单个 workflow 节点，将节点输出合并回 state，并记录 step trace。

        设计原因：
        - 所有节点都应遵循同一套运行记录格式
        - 节点失败时仍应在 state 中保留失败 trace，便于定位故障位置
        - runtime 不吞掉异常，调用方仍能感知真实失败
        """
        started_at = _utc_now_iso()

        try:
            result = node_func(state)
            state.update(result)
            self._record_step(
                state=state,
                step_name=step_name,
                result=result,
                status="completed",
                started_at=started_at,
                ended_at=_utc_now_iso(),
            )
            return result
        except Exception as exc:
            self.status = "failed"
            self.ended_at = _utc_now_iso()
            self._record_step(
                state=state,
                step_name=step_name,
                result={},
                status="failed",
                started_at=started_at,
                ended_at=self.ended_at,
                error=str(exc),
            )
            raise

    def _record_step(
        self,
        *,
        state: Dict[str, Any],
        step_name: str,
        result: Dict[str, Any],
        status: str,
        started_at: str,
        ended_at: str,
        error: str = "",
    ) -> None:
        """
        记录单个节点的摘要信息。

        当前实现只记录数量级指标和关键状态，避免将大段 page_content 写入 trace。
        完整数据仍保存在 state 与专门 artifacts 中。
        """
        trace = state.setdefault("debug_trace", [])
        summary: Dict[str, Any] = {
            "step": step_name,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "keys": sorted(result.keys()),
        }

        if error:
            summary["error"] = error

        if "search_queries" in result:
            summary["search_query_count"] = len(result.get("search_queries", []))
        if "search_results" in result:
            summary["search_result_count"] = len(result.get("search_results", []))
        if "page_results" in result:
            page_results = result.get("page_results", [])
            summary["page_result_count"] = len(page_results)
            summary["page_read_success_count"] = _count_successful_page_reads(page_results)
            summary["page_read_fallback_count"] = _count_fallback_page_reads(page_results)
        if "evidence_cards" in result:
            summary["evidence_card_count"] = len(result.get("evidence_cards", []))
        if "evidence_gaps" in result:
            summary["evidence_gaps"] = result.get("evidence_gaps", [])
        if "needs_retry" in result:
            summary["needs_retry"] = result.get("needs_retry", False)
        if "rewritten_queries" in result:
            summary["rewritten_query_count"] = len(result.get("rewritten_queries", []))
        if "notes" in result:
            summary["note_count"] = len(result.get("notes", []))
        if "final_report" in result:
            summary["final_report_length"] = len(result.get("final_report", ""))
        if "report_validation" in result:
            summary["report_validation_valid"] = result.get("report_validation", {}).get("valid", False)

        trace.append(summary)

    def build_summary(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成单次 research run 的结构化摘要。

        摘要用于终端输出、debug_data/latest_run_summary.json 和后续展示层读取。
        """
        if self.status == "running":
            self.status = "completed"
            self.ended_at = _utc_now_iso()

        page_results = state.get("page_results", [])
        report_validation = state.get("report_validation", {})

        history_artifacts = self._build_history_artifact_paths()

        return {
            "run_id": self.run_id,
            "question": self.question,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "search_queries": len(state.get("search_queries", [])),
            "search_results": len(state.get("search_results", [])),
            "page_results": len(page_results),
            "page_read_success_count": _count_successful_page_reads(page_results),
            "page_read_fallback_count": _count_fallback_page_reads(page_results),
            "evidence_cards": len(state.get("evidence_cards", [])),
            "needs_retry": state.get("needs_retry", False),
            "retry_count": state.get("retry_count", 0),
            "notes": len(state.get("notes", [])),
            "final_report_length": len(state.get("final_report", "")),
            "report_validation_valid": report_validation.get("valid"),
            "debug_trace": state.get("debug_trace", []),
            "artifacts": history_artifacts,
            "latest_artifacts": self._build_latest_artifact_paths(),
        }

    def save_artifacts(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        保存 full v2 debug 的标准产物。

        输出：
        - 返回 run summary，调用方可直接用于终端展示
        """
        summary = self.build_summary(state)
        state["run_summary"] = summary

        self._save_latest_artifacts(state, summary)
        self._save_history_artifacts(state, summary)
        self._update_run_index(summary)

        return summary

    def _build_latest_artifact_paths(self) -> Dict[str, str]:
        """
        构造 latest artifacts 的路径索引。
        """
        return {
            "state": str(self.artifact_dir / "latest_run_state.json"),
            "evidence_cards": str(self.artifact_dir / "latest_evidence_cards.json"),
            "report": str(self.artifact_dir / "latest_report.md"),
            "summary": str(self.artifact_dir / "latest_run_summary.json"),
        }

    def _build_history_artifact_paths(self) -> Dict[str, str]:
        """
        构造当前 run 专属 artifacts 的路径索引。
        """
        run_dir = self.artifact_dir / "runs" / self.run_id
        return {
            "state": str(run_dir / "state.json"),
            "evidence_cards": str(run_dir / "evidence_cards.json"),
            "report": str(run_dir / "report.md"),
            "summary": str(run_dir / "summary.json"),
        }

    def _save_latest_artifacts(self, state: Dict[str, Any], summary: Dict[str, Any]) -> None:
        """
        覆盖保存最近一次运行产物。

        设计原因：
        - latest_* 文件便于调试时快速打开最近一次结果
        - 该路径保持向后兼容，不影响现有 debug 查看习惯
        """
        self._save_json("latest_run_state.json", state)
        self._save_json("latest_evidence_cards.json", state.get("evidence_cards", []))
        self._save_text("latest_report.md", state.get("final_report", ""))
        self._save_json("latest_run_summary.json", summary)

    def _save_history_artifacts(self, state: Dict[str, Any], summary: Dict[str, Any]) -> None:
        """
        保存当前 run 的历史产物。

        每次运行都会写入 debug_data/runs/{run_id}/，用于后续复盘和多次运行对比。
        """
        run_prefix = f"runs/{self.run_id}"
        self._save_json(f"{run_prefix}/state.json", state)
        self._save_json(f"{run_prefix}/evidence_cards.json", state.get("evidence_cards", []))
        self._save_text(f"{run_prefix}/report.md", state.get("final_report", ""))
        self._save_json(f"{run_prefix}/summary.json", summary)

    def _build_index_record(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        从完整 run summary 中提取轻量索引记录。
        """
        return {
            "run_id": summary.get("run_id", ""),
            "question": summary.get("question", ""),
            "status": summary.get("status", ""),
            "started_at": summary.get("started_at", ""),
            "ended_at": summary.get("ended_at", ""),
            "search_queries": summary.get("search_queries", 0),
            "page_results": summary.get("page_results", 0),
            "page_read_fallback_count": summary.get("page_read_fallback_count", 0),
            "evidence_cards": summary.get("evidence_cards", 0),
            "needs_retry": summary.get("needs_retry", False),
            "retry_count": summary.get("retry_count", 0),
            "report_validation_valid": summary.get("report_validation_valid"),
            "summary_path": summary.get("artifacts", {}).get("summary", ""),
        }

    def _update_run_index(self, summary: Dict[str, Any]) -> None:
        """
        更新 runs/index.json 轻量索引。

        策略：
        - 同 run_id 只保留最新记录
        - 按 started_at 倒序排列
        - 最多保留 RUN_HISTORY_LIMIT 条记录，避免本地 debug 产物无限增长
        """
        index_path = "runs/index.json"
        records = self._load_json(index_path, default=[])
        if not isinstance(records, list):
            records = []

        new_record = self._build_index_record(summary)
        records = [
            item
            for item in records
            if item.get("run_id") != new_record["run_id"]
        ]
        records.append(new_record)
        records.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        records = records[:RUN_HISTORY_LIMIT]

        self._save_json(index_path, records)

    def _save_json(self, filename: str, data: Any) -> None:
        """
        将 JSON 产物保存到 artifact_dir。
        """
        path = self.artifact_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_text(self, filename: str, content: str) -> None:
        """
        将文本产物保存到 artifact_dir。
        """
        path = self.artifact_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _load_json(self, filename: str, default: Any) -> Any:
        """
        从 artifact_dir 读取 JSON 文件。

        读取失败或文件不存在时返回 default，用于保持本地运行链路稳定。
        """
        path = self.artifact_dir / filename
        if not path.exists():
            return default

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
