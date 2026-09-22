"""谱系记录的读取、领域规则校验与分级视图。

领域规则：
- 器物物理身份（artifact）与学术判断（claims）分离保存；
- 任何观察、定名、流转事件、判断都必须引用已登记的来源；
- 判断被推翻或取代时只改状态（superseded/refuted），记录保留；
- 公众视图只含馆方授权的内容，未公开材料默认不出现。
"""

import json
from pathlib import Path

SECTIONS = ("observations", "namings", "provenance_events", "claims", "images")

ID_KEYS = {
    "observations": "observation_id",
    "namings": "naming_id",
    "provenance_events": "event_id",
    "claims": "claim_id",
    "images": "image_id",
}

REQUIRED_TOP = {
    "record_id",
    "schema_version",
    "artifact",
    "sources",
    "observations",
    "namings",
    "provenance_events",
    "claims",
    "rights",
}


def load_record(path: Path) -> dict:
    """读取谱系记录并通过全部领域规则校验，不合格时抛出 ValueError。"""
    record = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_record(record)
    if problems:
        raise ValueError("谱系记录不合格：" + "；".join(problems))
    return record


def validate_record(record: dict) -> list[str]:
    """返回违反领域规则的问题列表，空列表表示合格。"""
    problems = []
    missing = REQUIRED_TOP - set(record)
    if missing:
        problems.append(f"缺少必要字段：{sorted(missing)}")
        return problems

    source_ids = {s["source_id"] for s in record["sources"]}

    for section in SECTIONS:
        items = record.get(section, [])
        id_key = ID_KEYS[section]
        seen = set()
        for item in items:
            item_id = item.get(id_key)
            if item_id in seen:
                problems.append(f"{section} 中 {item_id} 重复")
            seen.add(item_id)
            ref = item.get("source_id")
            if ref is not None and ref not in source_ids:
                problems.append(f"{section} 中 {item_id} 引用了未登记来源 {ref}")

    claim_ids = {c["claim_id"] for c in record["claims"]}
    for claim in record["claims"]:
        for field in ("proposed_by", "source_id", "valid_from"):
            if not claim.get(field):
                problems.append(f"判断 {claim.get('claim_id')} 缺少 {field}（结论须可回溯提出者、来源与有效时间）")
        if claim.get("kind") == "same_as" and not claim.get("target_record_id"):
            problems.append(f"判断 {claim['claim_id']} 为同一性关联但缺少 target_record_id")
        supersedes = claim.get("supersedes")
        if supersedes is not None:
            if supersedes not in claim_ids:
                problems.append(f"判断 {claim['claim_id']} 取代的 {supersedes} 不存在")
            else:
                old = next(c for c in record["claims"] if c["claim_id"] == supersedes)
                if old["status"] not in ("superseded", "refuted"):
                    problems.append(f"判断 {supersedes} 已被取代但状态仍为 {old['status']}（历史判断须保留并标记失效）")

    for naming in record["namings"]:
        if naming["status"] == "superseded" and naming.get("valid_to") is None:
            problems.append(f"定名 {naming['naming_id']} 已被取代但缺少失效时间 valid_to")
        if naming["status"] == "current" and naming.get("valid_to") is not None:
            problems.append(f"定名 {naming['naming_id']} 为现行定名但带有失效时间")

    known_ids = set()
    for section in SECTIONS:
        known_ids.update(item[ID_KEYS[section]] for item in record.get(section, []))
    for policy in record["rights"]["policies"]:
        target = policy["applies_to"]
        if target not in SECTIONS and target not in known_ids:
            problems.append(f"授权策略 {policy['policy_id']} 指向不存在的栏目或条目 {target}")

    return problems


def _default_allowed(record: dict, section: str, item: dict, audience: str) -> bool:
    if audience != "public":
        return True
    if section == "images":
        return item.get("visibility") == "public"
    return record["rights"]["default_visibility"] == "public"


def _allowed(record: dict, section: str, item: dict, audience: str) -> bool:
    """条目级策略优先于栏目级策略，同级策略以后出现者为准。"""
    id_key = ID_KEYS[section]
    item_id = item.get(id_key)
    decision = None
    for policy in record["rights"]["policies"]:
        if policy["audience"] == audience and policy["applies_to"] == section:
            decision = policy["allowed"]
    for policy in record["rights"]["policies"]:
        if policy["audience"] == audience and policy["applies_to"] == item_id:
            decision = policy["allowed"]
    if decision is None:
        decision = _default_allowed(record, section, item, audience)
    return decision


def view_for(record: dict, audience: str = "public") -> dict:
    """按受众过滤记录。公众视图不含授权策略本身，避免泄露受限条目的存在。"""
    view = {
        "record_id": record["record_id"],
        "schema_version": record["schema_version"],
        "artifact": record["artifact"],
        "sources": record["sources"],
    }
    for section in SECTIONS:
        view[section] = [
            item
            for item in record.get(section, [])
            if _allowed(record, section, item, audience)
        ]
    if audience != "public":
        view["rights"] = record["rights"]
    return view
