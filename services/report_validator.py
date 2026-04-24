"""
报告引用校验模块。

模块职责：
1. 从最终报告中提取正文引用编号与参考来源编号
2. 将报告中的编号与 report_builder 生成的候选来源编号进行比对
3. 输出结构化校验结果，便于 debug、测试和后续 CI 观测

设计目标：
1. 将引用校验从报告生成 prompt 和后处理逻辑中拆出
2. 保持校验逻辑确定、轻量、无模型依赖
3. 为后续扩展 report verifier 保留清晰边界

当前限制：
- 仅校验形如 [1]、[2] 的数字引用编号
- 不判断引用内容是否真正支撑对应结论
- 参考来源章节默认识别 Markdown 标题“# 参考来源”
"""

import re
from typing import Any, Dict, List, Set


REFERENCE_HEADING = "# 参考来源"


def _sorted_ids(values: Set[int]) -> List[int]:
    """
    将编号集合转换为稳定排序的列表。
    """
    return sorted(values)


def _split_reference_section(report: str) -> Dict[str, Any]:
    """
    将报告拆分为正文部分和参考来源部分。

    设计原因：
    - 正文引用编号用于判断报告实际引用了哪些来源
    - 参考来源章节编号用于判断最终来源列表是否完整
    - 两者需要分开提取，避免把参考来源列表自身误认为正文引用
    """
    report = report or ""
    heading_index = report.find(REFERENCE_HEADING)

    if heading_index < 0:
        return {
            "body": report,
            "references": "",
            "has_reference_section": False,
        }

    return {
        "body": report[:heading_index],
        "references": report[heading_index:],
        "has_reference_section": True,
    }


def extract_citation_ids(text: str) -> List[int]:
    """
    从文本中提取形如 [1]、[2] 的引用编号。

    返回值保持升序去重，便于测试和日志观察。
    """
    ids = {
        int(match)
        for match in re.findall(r"\[(\d+)\]", text or "")
    }
    return _sorted_ids(ids)


def extract_reference_ids(reference_text: str) -> List[int]:
    """
    从参考来源章节中提取实际列出的来源编号。

    当前仅统计行首编号，例如：
    [1] Source title

    设计原因：
    - 参考来源条目应以编号开头
    - 避免把 URL、说明文字或正文片段中的 [n] 误判为来源条目
    """
    ids = {
        int(match)
        for match in re.findall(r"(?m)^\[(\d+)\]", reference_text or "")
    }
    return _sorted_ids(ids)


def collect_allowed_source_ids(unique_sources: List[Dict[str, Any]]) -> List[int]:
    """
    从候选引用来源中提取允许使用的 source_id。

    输入：
    - unique_sources: report_builder 返回的候选来源列表

    输出：
    - 升序去重后的 source_id 列表
    """
    ids = {
        item.get("source_id")
        for item in unique_sources
        if isinstance(item.get("source_id"), int)
    }
    return _sorted_ids(ids)


def validate_report_citations(
    report: str,
    unique_sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    校验最终报告中的来源编号是否与候选来源一致。

    输出字段：
    - valid: 是否通过当前引用校验
    - cited_ids: 正文中引用过的编号
    - reference_ids: 参考来源章节列出的编号
    - allowed_ids: 候选来源允许使用的编号
    - invalid_citation_ids: 正文引用了但不在候选来源中的编号
    - invalid_reference_ids: 参考来源列出但不在候选来源中的编号
    - missing_reference_ids: 正文引用过但参考来源未列出的候选编号
    - has_reference_section: 是否存在参考来源章节

    当前校验边界：
    - 校验编号合法性和参考列表完整性
    - 不校验证据内容与结论之间的语义支撑关系
    """
    sections = _split_reference_section(report)

    cited_ids = set(extract_citation_ids(sections["body"]))
    reference_ids = set(extract_reference_ids(sections["references"]))
    allowed_ids = set(collect_allowed_source_ids(unique_sources))

    invalid_citation_ids = cited_ids - allowed_ids
    invalid_reference_ids = reference_ids - allowed_ids
    missing_reference_ids = (cited_ids & allowed_ids) - reference_ids

    valid = (
        sections["has_reference_section"]
        and not invalid_citation_ids
        and not invalid_reference_ids
        and not missing_reference_ids
    )

    return {
        "valid": valid,
        "cited_ids": _sorted_ids(cited_ids),
        "reference_ids": _sorted_ids(reference_ids),
        "allowed_ids": _sorted_ids(allowed_ids),
        "invalid_citation_ids": _sorted_ids(invalid_citation_ids),
        "invalid_reference_ids": _sorted_ids(invalid_reference_ids),
        "missing_reference_ids": _sorted_ids(missing_reference_ids),
        "has_reference_section": sections["has_reference_section"],
    }
