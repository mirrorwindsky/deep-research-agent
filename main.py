from graphs.research_graph import build_research_graph


def main():
    """
    项目主入口。

    当前只负责：
    1. 获取用户输入
    2. 构建 research graph
    3. 执行 graph
    4. 打印最终报告

    注意：
    main.py 不再负责模型调用、prompt 内容、搜索实现细节。
    这些都已经被拆到别的模块中了。
    """
    question = input("请输入你的研究问题：\n> ").strip()

    if not question:
        print("研究问题不能为空。")
        return

    app = build_research_graph()

    # 把初始状态传进去
    result = app.invoke({"question": question})

    print("\n========== 最终研究报告 ==========\n")
    print(result.get("final_report", "未生成报告"))


if __name__ == "__main__":
    main()