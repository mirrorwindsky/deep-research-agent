"""
项目命令行主入口。

职责：
1. 读取用户输入的研究问题
2. 通过 runtime 执行完整 research workflow
3. 输出最终研究报告

说明：
- 该文件只保留入口职责
- 模型调用、节点逻辑、搜索实现、workflow 编排均已拆分到独立模块
"""

import argparse

from services.cli_view import CliRuntimeView, configure_utf8_console
from services.run_history import RunHistory
from services.workflow_runner import run_full_v2_workflow


def _parse_args():
    """
    解析 CLI 参数。

    当前支持：
    - 默认无参数：执行一次完整 research workflow
    - --runs：列出最近 run history
    - --last：显示最近一次 run 的报告和摘要
    - --show-run <run_id>：显示指定 run 的报告和摘要
    """
    parser = argparse.ArgumentParser(
        description="Deep Research Agent v2 CLI",
    )
    history_group = parser.add_mutually_exclusive_group()
    history_group.add_argument(
        "--runs",
        action="store_true",
        help="列出最近的 run history。",
    )
    history_group.add_argument(
        "--last",
        action="store_true",
        help="显示最近一次 run 的报告和摘要。",
    )
    history_group.add_argument(
        "--show-run",
        metavar="RUN_ID",
        help="显示指定 run_id 的报告和摘要。",
    )
    return parser.parse_args()


def _handle_history_command(args, view: CliRuntimeView) -> bool:
    """
    处理 run history 查询命令。

    返回：
    - True: 已处理 history 命令，主流程应直接结束
    - False: 未命中 history 命令，应继续执行 research workflow
    """
    history = RunHistory()

    if args.runs:
        view.print_run_history(history.list_runs())
        return True

    if args.last:
        result = history.load_latest_run()
        view.print_history_run(
            summary=result["summary"],
            report=result["report"],
        )
        return True

    if args.show_run:
        result = history.load_run(args.show_run)
        view.print_history_run(
            summary=result["summary"],
            report=result["report"],
        )
        return True

    return False


def main():
    """
    执行项目主流程。

    流程：
    1. 获取研究问题
    2. 校验输入是否为空
    3. 通过 runtime 执行 full v2 workflow
    4. 保存标准运行产物
    5. 输出最终报告
    """
    configure_utf8_console()
    args = _parse_args()
    view = CliRuntimeView()

    if _handle_history_command(args, view):
        return

    question = input("请输入你的研究问题：\n> ").strip()

    # 空输入直接返回，避免构建无意义任务
    if not question:
        print("研究问题不能为空。")
        return

    view.print_header(question)

    result = run_full_v2_workflow(
        question=question,
        save_artifacts=True,
        on_step_start=view.on_step_start,
        on_step_complete=view.on_step_complete,
        on_report_stream=view.on_report_stream,
        suppress_node_logs=True,
    )
    state = result["state"]
    summary = result["summary"]

    if view.report_stream_started:
        view.print_report_stream_end()

    view.print_run_result(
        summary=summary,
        report=state.get("final_report", ""),
        include_artifacts=True,
        include_report=not view.report_stream_started,
        include_steps=not view.report_stream_started,
    )


if __name__ == "__main__":
    main()
