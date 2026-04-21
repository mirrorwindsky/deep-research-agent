# debug_run.py

"""
本地调试入口。

模块职责：
1. 提供 plan / search / synthesize / report 等分阶段调试模式。
2. 支持将中间产物保存到 debug_data 目录，便于复盘和复用样本。
3. 提供完整 v2 workflow 调试入口，用于观察页面读取、证据构建、质量判断、补搜和报告生成过程。

说明：
- 本文件不替代 main.py。
- 本文件主要用于节点级调试、真实链路验证和中间状态留存。
"""

import json
from pathlib import Path

from agents.researcher import (
    build_evidence_cards_node,
    judge_search_quality_node,
    plan_node,
    read_pages_node,
    report_node,
    rewrite_query_node,
    search_node,
    synthesize_evidence_node,
    synthesize_node,
)

# 调试数据目录。
# 用于保存 search_results、page_results、evidence_cards、notes、report 等中间样本。
DEBUG_DATA_DIR = Path("debug_data")
DEBUG_DATA_DIR.mkdir(exist_ok=True)


def save_json(filename: str, data):
    """
    将数据保存为 JSON 文件。

    参数：
    - filename: 保存文件名。
    - data: 待保存的数据。
    """
    path = DEBUG_DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已保存到: {path}")


def load_json(filename: str):
    """
    从 debug_data 目录加载 JSON 文件。

    参数：
    - filename: 待读取的文件名。

    返回：
    - 解析后的 JSON 数据。
    """
    path = DEBUG_DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_text(filename: str, content: str):
    """
    将文本内容保存到 debug_data 目录。

    参数：
    - filename: 保存文件名。
    - content: 待写入的文本内容。
    """
    path = DEBUG_DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"已保存到: {path}")


def run_plan_only():
    """
    仅执行 plan_node。

    适用场景：
    - 调试 planner prompt。
    - 观察 query 生成结果。
    - 验证中英文混合 query 策略。
    """
    question = input("请输入研究问题：\n> ").strip()
    state = {"question": question}
    result = plan_node(state)

    print("\n===== PLAN RESULT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_search_only():
    """
    仅执行 search_node。

    适用场景：
    - 调试真实搜索质量。
    - 观察来源排序结果。
    - 验证去重与截断逻辑。
    """
    print("请输入 query，每行一条，输入空行结束：")
    queries = []

    while True:
        line = input("> ").strip()
        if not line:
            break
        queries.append(line)

    state = {"search_queries": queries}
    result = search_node(state)

    print("\n===== SEARCH RESULT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    should_save = input("\n是否保存 search_results 到 debug_data？(y/n)\n> ").strip().lower()
    if should_save == "y":
        save_json("sample_search_results.json", result.get("search_results", []))


def run_synthesize_only():
    """
    仅执行 synthesize_node。

    适用场景：
    - 使用已保存的 search_results 调试笔记提炼效果。
    - 避免重复调用搜索接口。
    """
    filename = input("请输入 search_results 文件名（位于 debug_data）：\n> ").strip()
    search_results = load_json(filename)

    question = input("请输入原始问题：\n> ").strip()

    state = {
        "question": question,
        "search_results": search_results,
    }
    result = synthesize_node(state)

    print("\n===== SYNTHESIZE RESULT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    should_save = input("\n是否保存 notes 到 debug_data？(y/n)\n> ").strip().lower()
    if should_save == "y":
        save_json("sample_notes.json", result.get("notes", []))


def run_report_only():
    """
    仅执行 report_node。

    适用场景：
    - 使用本地保存的 notes 和 search_results 调试最终报告输出。
    - 验证引用来源收口与报告结构。
    """
    question = input("请输入原始问题：\n> ").strip()

    notes_file = input("请输入 notes 文件名（位于 debug_data）：\n> ").strip()
    notes = load_json(notes_file)

    results_file = input("请输入 search_results 文件名（位于 debug_data）：\n> ").strip()
    search_results = load_json(results_file)

    state = {
        "question": question,
        "notes": notes,
        "search_results": search_results,
    }
    result = report_node(state)

    print("\n===== REPORT RESULT =====")
    print(result.get("final_report", ""))


def run_read_pages_only():
    """
    执行 search_node + read_pages_node。

    适用场景：
    - 验证真实页面读取能力。
    - 观察 page_content 和 page_summary 的质量。
    - 快速检查 GitHub / docs 页面清洗效果。
    """
    print("请输入 query，每行一条，输入空行结束：")
    queries = []

    while True:
        line = input("> ").strip()
        if not line:
            break
        queries.append(line)

    state = {"search_queries": queries}

    search_result = search_node(state)
    state.update(search_result)

    read_result = read_pages_node(state)

    print("\n===== READ PAGES RESULT =====")
    print(json.dumps(read_result, ensure_ascii=False, indent=2))

    should_save = input("\n是否保存 page_results 到 debug_data？(y/n)\n> ").strip().lower()
    if should_save == "y":
        save_json("sample_page_results.json", read_result.get("page_results", []))


def run_build_evidence_only():
    """
    执行 search_node + read_pages_node + build_evidence_cards_node。

    适用场景：
    - 独立观察 evidence card 构建效果。
    - 验证 page_content / page_summary 是否能够产生可用 claim 和 evidence。
    - 避免每次都执行完整 graph 与最终报告生成。
    """
    question = input("请输入原始研究问题：\n> ").strip()

    print("请输入 query，每行一条，输入空行结束：")
    queries = []

    while True:
        line = input("> ").strip()
        if not line:
            break
        queries.append(line)

    if not queries and question:
        queries = [question]

    state = {
        "question": question,
        "search_queries": queries,
    }

    search_result = search_node(state)
    state.update(search_result)

    read_result = read_pages_node(state)
    state.update(read_result)

    evidence_result = build_evidence_cards_node(state)

    print("\n===== EVIDENCE CARDS RESULT =====")
    print(json.dumps(evidence_result, ensure_ascii=False, indent=2))

    should_save = input("\n是否保存 evidence_cards 到 debug_data？(y/n)\n> ").strip().lower()
    if should_save == "y":
        save_json("sample_evidence_cards.json", evidence_result.get("evidence_cards", []))

    should_save_pages = input("\n是否同时保存 page_results 到 debug_data？(y/n)\n> ").strip().lower()
    if should_save_pages == "y":
        save_json("sample_page_results.json", read_result.get("page_results", []))


def _record_debug_step(state, step_name: str, result):
    """
    记录 full v2 debug 中单个节点的简要输出。

    完整 state 会在运行结束时保存。debug_trace 只保留节点名、输出字段和关键数量，
    用于快速复盘 agent 决策路径，避免在终端输出大段页面正文。
    """
    trace = state.setdefault("debug_trace", [])
    summary = {
        "step": step_name,
        "keys": sorted(result.keys()),
    }

    if "search_queries" in result:
        summary["search_query_count"] = len(result.get("search_queries", []))
    if "search_results" in result:
        summary["search_result_count"] = len(result.get("search_results", []))
    if "page_results" in result:
        summary["page_result_count"] = len(result.get("page_results", []))
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

    trace.append(summary)


def _run_debug_node(state, step_name: str, node_func):
    """
    执行单个 workflow 节点，将输出合并回 state，并记录 debug_trace。
    """
    print(f"\n===== RUNNING {step_name.upper()} =====")
    result = node_func(state)
    state.update(result)
    _record_debug_step(state, step_name, result)
    return result


def run_full_v2_debug():
    """
    执行完整 Deep Research Agent v2 本地调试链路。

    流程：
    plan -> search -> read_pages -> build_evidence_cards -> judge_search_quality
    -> 可选 rewrite/search/read/evidence/judge 补搜轮次
    -> synthesize_evidence -> report

    保存产物：
    - debug_data/latest_run_state.json
    - debug_data/latest_evidence_cards.json
    - debug_data/latest_report.md
    """
    question = input("请输入原始研究问题：\n> ").strip()
    if not question:
        print("研究问题不能为空。")
        return

    state = {
        "question": question,
        "debug_trace": [],
    }

    _run_debug_node(state, "plan", plan_node)
    _run_debug_node(state, "search", search_node)
    _run_debug_node(state, "read_pages", read_pages_node)
    _run_debug_node(state, "build_evidence_cards", build_evidence_cards_node)
    _run_debug_node(state, "judge_search_quality", judge_search_quality_node)

    if state.get("needs_retry", False):
        _run_debug_node(state, "rewrite_query", rewrite_query_node)
        _run_debug_node(state, "retry_search", search_node)
        _run_debug_node(state, "retry_read_pages", read_pages_node)
        _run_debug_node(state, "retry_build_evidence_cards", build_evidence_cards_node)
        _run_debug_node(state, "retry_judge_search_quality", judge_search_quality_node)

    _run_debug_node(state, "synthesize_evidence", synthesize_evidence_node)
    _run_debug_node(state, "report", report_node)

    save_json("latest_run_state.json", state)
    save_json("latest_evidence_cards.json", state.get("evidence_cards", []))
    save_text("latest_report.md", state.get("final_report", ""))

    print("\n===== FULL V2 DEBUG SUMMARY =====")
    print(f"search_queries: {len(state.get('search_queries', []))}")
    print(f"search_results: {len(state.get('search_results', []))}")
    print(f"page_results: {len(state.get('page_results', []))}")
    print(f"evidence_cards: {len(state.get('evidence_cards', []))}")
    print(f"needs_retry: {state.get('needs_retry', False)}")
    print(f"retry_count: {state.get('retry_count', 0)}")
    print(f"notes: {len(state.get('notes', []))}")
    print(f"final_report_length: {len(state.get('final_report', ''))}")


def main():
    """
    调试模式选择入口。
    """
    print("选择调试模式：")
    print("1. plan only")
    print("2. search only")
    print("3. synthesize only")
    print("4. report only")
    print("5. read pages only")
    print("6. build evidence only")
    print("7. full v2 debug")

    choice = input("> ").strip()

    if choice == "1":
        run_plan_only()
    elif choice == "2":
        run_search_only()
    elif choice == "3":
        run_synthesize_only()
    elif choice == "4":
        run_report_only()
    elif choice == "5":
        run_read_pages_only()
    elif choice == "6":
        run_build_evidence_only()
    elif choice == "7":
        run_full_v2_debug()
    else:
        print("无效选择。")


if __name__ == "__main__":
    main()
