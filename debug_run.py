# debug_run.py

"""
本地调试入口。

职责：
1. 提供 plan / search / synthesize / report 的分阶段调试模式
2. 支持将中间产物保存到 debug_data 目录
3. 降低局部调试时不必要的 API 消耗

说明：
- 该文件不替代 main.py
- 该文件用于节点级调试与样本复用
"""

import json
from pathlib import Path

from agents.researcher import (
    plan_node,
    report_node,
    search_node,
    synthesize_node,
    read_pages_node,
    build_evidence_cards_node,
    judge_search_quality_node,
    rewrite_query_node,
    synthesize_evidence_node,
)

# 调试数据目录。
# 用于保存 search_results、notes 等中间样本，便于后续重复使用。
DEBUG_DATA_DIR = Path("debug_data")
DEBUG_DATA_DIR.mkdir(exist_ok=True)


def save_json(filename: str, data):
    """
    将数据保存为 JSON 文件。

    参数：
    - filename: 保存文件名
    - data: 待保存数据
    """
    path = DEBUG_DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已保存到: {path}")


def load_json(filename: str):
    """
    从 debug_data 目录加载 JSON 文件。

    参数：
    - filename: 待读取文件名

    返回：
    - 解析后的 JSON 数据
    """
    path = DEBUG_DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_plan_only():
    """
    仅执行 plan_node。

    适用场景：
    - 调试 planner prompt
    - 观察 query 生成效果
    - 验证中英混合 query 策略
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
    - 调试真实搜索质量
    - 观察来源排序结果
    - 验证去重与截断逻辑
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
    - 使用已保存的 search_results 调试笔记提炼效果
    - 避免重复调用搜索接口
    """
    filename = input("请输入 search_results 文件名（放在 debug_data 中）：\n> ").strip()
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
    - 使用本地保存的 notes 和 search_results 调试最终报告输出
    - 验证引用来源收口与报告结构
    """
    question = input("请输入原始问题：\n> ").strip()

    notes_file = input("请输入 notes 文件名（放在 debug_data 中）：\n> ").strip()
    notes = load_json(notes_file)

    results_file = input("请输入 search_results 文件名（放在 debug_data 中）：\n> ").strip()
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
    执行 search_node + read_pages_node，用于验证真实页面读取能力。
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
    - 独立观察 evidence card 构建效果
    - 验证 page_content / page_summary 是否能产生可用 claim 与 evidence
    - 避免每次都执行完整 graph 与最终报告生成
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
    else:
        print("无效选择。")


if __name__ == "__main__":
    main()
