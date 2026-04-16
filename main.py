# main.py

"""
项目命令行主入口。

职责：
1. 读取用户输入的研究问题
2. 构建并执行 research graph
3. 输出最终研究报告

说明：
- 该文件只保留入口职责
- 模型调用、节点逻辑、搜索实现、graph 编排均已拆分到独立模块
"""

from graphs.research_graph import build_research_graph


def main():
    """
    执行项目主流程。

    流程：
    1. 获取研究问题
    2. 校验输入是否为空
    3. 构建 graph
    4. 执行 graph
    5. 输出最终报告
    """
    question = input("请输入你的研究问题：\n> ").strip()

    # 空输入直接返回，避免构建无意义任务
    if not question:
        print("研究问题不能为空。")
        return

    app = build_research_graph()

    # 传入初始状态，只包含原始问题
    result = app.invoke({"question": question})

    print("\n========== 最终研究报告 ==========\n")
    print(result.get("final_report", "未生成报告"))


if __name__ == "__main__":
    main()