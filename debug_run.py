import json
from pathlib import Path

from agents.researcher import (
    plan_node,
    search_node,
    synthesize_node,
    report_node,
)

DEBUG_DATA_DIR = Path("debug_data")
DEBUG_DATA_DIR.mkdir(exist_ok=True)


def save_json(filename: str, data):
    path = DEBUG_DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已保存到: {path}")


def load_json(filename: str):
    path = DEBUG_DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_plan_only():
    question = input("请输入研究问题：\n> ").strip()
    state = {"question": question}
    result = plan_node(state)

    print("\n===== PLAN RESULT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_search_only():
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


def main():
    print("选择调试模式：")
    print("1. plan only")
    print("2. search only")
    print("3. synthesize only")
    print("4. report only")

    choice = input("> ").strip()

    if choice == "1":
        run_plan_only()
    elif choice == "2":
        run_search_only()
    elif choice == "3":
        run_synthesize_only()
    elif choice == "4":
        run_report_only()
    else:
        print("无效选择。")


if __name__ == "__main__":
    main()