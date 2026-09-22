"""谱系声明的校验、修订与公开视图。

谱系库不直接改写任何结论：每次定名、断代、归属与流转判断都
记录为一条带来源、提出者与有效时间的声明（claim）。新证据只能
以新声明取代旧声明（supersede）或撤回（retract），旧声明保留在
历史中，旧目录的定名不会消失。器物之间的“同一器物”判断记录为
身份关联（identity link），沿 candidate -> accepted / rejected 单向
流转，被否决的关联同样保留，不做记录合并。同一谓词允许多条
active 声明并存，以便并列比较相互竞争的年代与流转假说。
"""

VISIBILITIES = ("public", "restricted", "internal")
CLAIM_STATUS = ("active", "superseded", "retracted")
LINK_STATUS = ("candidate", "accepted", "rejected")
CONFIDENCES = ("high", "medium", "low")
PREDICATES = (
    "has_name",
    "has_measurement",
    "has_decoration",
    "has_rework_trace",
    "dated_to",
    "from_culture",
    "held_by",
    "formerly_owned_by",
    "transferred_in",
    "published_in",
    "depicted_in",
    "has_license",
)
SOURCE_KINDS = (
    "catalogue",
    "publication",
    "inspection",
    "correspondence",
    "excavation_report",
    "sale_record",
)

_REQUIRED_CLAIM_FIELDS = {
    "claim_id",
    "subject",
    "predicate",
    "value",
    "source",
    "proposer",
    "proposed_at",
    "confidence",
    "status",
    "visibility",
}
_REQUIRED_LINK_FIELDS = {
    "link_id",
    "artifact_a",
    "artifact_b",
    "link_status",
    "rationale",
    "proposer",
    "proposed_at",
    "visibility",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_claim(claim):
    """检查单条声明的字段、枚举与可追溯性。"""
    _require(isinstance(claim, dict), "声明必须是对象")
    _require(_REQUIRED_CLAIM_FIELDS.issubset(claim), "声明缺少必要字段")
    _require(claim["predicate"] in PREDICATES, f"未知谓词: {claim['predicate']}")
    _require(claim["confidence"] in CONFIDENCES, f"未知可信度: {claim['confidence']}")
    _require(claim["status"] in CLAIM_STATUS, f"未知声明状态: {claim['status']}")
    _require(claim["visibility"] in VISIBILITIES, f"未知可见性: {claim['visibility']}")
    source = claim["source"]
    _require(isinstance(source, dict), "来源必须是对象")
    _require(source.get("kind") in SOURCE_KINDS, f"未知来源类型: {source.get('kind')}")
    _require(bool(source.get("ref")), "声明必须注明原始记录")
    _require(bool(claim["proposer"]), "声明必须注明提出者")
    _require(bool(claim["proposed_at"]), "声明必须注明提出时间")
    if claim["status"] == "superseded":
        _require(bool(claim.get("superseded_by")), "被取代的声明必须指向取代者")
    else:
        _require(not claim.get("superseded_by"), "未取代的声明不得指向取代者")
    return claim


def validate_link(link):
    """检查单条身份关联的字段与状态一致性。"""
    _require(isinstance(link, dict), "身份关联必须是对象")
    _require(_REQUIRED_LINK_FIELDS.issubset(link), "身份关联缺少必要字段")
    _require(link["link_status"] in LINK_STATUS, f"未知关联状态: {link['link_status']}")
    _require(link["visibility"] in VISIBILITIES, f"未知可见性: {link['visibility']}")
    _require(link["artifact_a"] != link["artifact_b"], "身份关联两端不能是同一记录")
    if link["link_status"] == "candidate":
        _require(not link.get("decided_by") and not link.get("decided_at"),
                 "候选关联不得带有裁定信息")
    else:
        _require(bool(link.get("decided_by")) and bool(link.get("decided_at")),
                 "已裁定的关联必须注明裁定者与裁定时间")
    return link


def validate_store(store):
    """检查整库结构、标识唯一性与取代关系闭合。"""
    _require(isinstance(store, dict), "库必须是对象")
    _require(store.get("domain") == "jade-provenance-atlas", "领域标识不符")
    _require(isinstance(store.get("version"), int) and store["version"] >= 1, "版本无效")
    claims = store.get("claims")
    links = store.get("identity_links")
    _require(isinstance(claims, list) and isinstance(links, list), "库缺少声明或关联列表")
    ids = set()
    for claim in claims:
        validate_claim(claim)
        _require(claim["claim_id"] not in ids, f"声明标识重复: {claim['claim_id']}")
        ids.add(claim["claim_id"])
    for claim in claims:
        if claim["status"] == "superseded":
            _require(claim["superseded_by"] in ids,
                     f"取代者不存在: {claim['superseded_by']}")
    link_ids = set()
    for link in links:
        validate_link(link)
        _require(link["link_id"] not in link_ids, f"关联标识重复: {link['link_id']}")
        link_ids.add(link["link_id"])
    return store


def new_store(version=1):
    """返回一个空的谱系库。"""
    return {
        "domain": "jade-provenance-atlas",
        "version": version,
        "claims": [],
        "identity_links": [],
    }


def _find_claim(store, claim_id):
    for claim in store["claims"]:
        if claim["claim_id"] == claim_id:
            return claim
    raise ValueError(f"声明不存在: {claim_id}")


def _find_link(store, link_id):
    for link in store["identity_links"]:
        if link["link_id"] == link_id:
            return link
    raise ValueError(f"身份关联不存在: {link_id}")


def add_claim(store, claim):
    """追加一条新声明。声明只能以 active 状态进入库中。"""
    validate_claim(claim)
    _require(claim["status"] == "active", "新声明必须以 active 状态入库")
    _require(all(c["claim_id"] != claim["claim_id"] for c in store["claims"]),
             f"声明标识重复: {claim['claim_id']}")
    store["claims"].append(claim)
    return claim


def supersede_claim(store, old_id, new_claim):
    """以新声明取代旧声明。旧声明标记为 superseded 并保留在历史中。"""
    old = _find_claim(store, old_id)
    _require(old["status"] == "active", f"只能取代 active 状态的声明: {old_id}")
    add_claim(store, new_claim)
    old["status"] = "superseded"
    old["superseded_by"] = new_claim["claim_id"]
    if not old.get("valid_to"):
        old["valid_to"] = new_claim["proposed_at"]
    return old


def retract_claim(store, claim_id):
    """撤回一条声明（证据被证伪且没有替代结论）。声明保留在历史中。"""
    claim = _find_claim(store, claim_id)
    _require(claim["status"] == "active", f"只能撤回 active 状态的声明: {claim_id}")
    claim["status"] = "retracted"
    return claim


def add_identity_link(store, link):
    """登记一条“同一器物”候选关联。"""
    validate_link(link)
    _require(link["link_status"] == "candidate", "新关联必须以 candidate 状态入库")
    _require(all(l["link_id"] != link["link_id"] for l in store["identity_links"]),
             f"关联标识重复: {link['link_id']}")
    store["identity_links"].append(link)
    return link


def decide_identity_link(store, link_id, decision, decided_by, decided_at):
    """裁定候选关联为 accepted 或 rejected。裁定只能进行一次。"""
    _require(decision in ("accepted", "rejected"), f"未知裁定: {decision}")
    link = _find_link(store, link_id)
    _require(link["link_status"] == "candidate", f"关联已被裁定，不可更改: {link_id}")
    link["link_status"] = decision
    link["decided_by"] = decided_by
    link["decided_at"] = decided_at
    return link


def active_claims(store, subject=None, predicate=None):
    """返回当前有效的声明，可按主体与谓词过滤。竞争假说会并列返回。"""
    return [
        c for c in store["claims"]
        if c["status"] == "active"
        and (subject is None or c["subject"] == subject)
        and (predicate is None or c["predicate"] == predicate)
    ]


def claim_history(store, subject=None, predicate=None):
    """返回全部状态的声明（含被取代与撤回的旧目录记载），按提出时间排序。"""
    claims = [
        c for c in store["claims"]
        if (subject is None or c["subject"] == subject)
        and (predicate is None or c["predicate"] == predicate)
    ]
    return sorted(claims, key=lambda c: c["proposed_at"])


def public_view(store):
    """投影出公众可见的内容：只保留 public 级别的声明与关联。

    被取代的旧定名只要本身是 public 就仍然可见，公众可以看到
    定名沿革；restricted 与 internal 材料完全不进入公开视图。
    """
    return {
        "domain": store["domain"],
        "version": store["version"],
        "claims": [c for c in store["claims"] if c["visibility"] == "public"],
        "identity_links": [l for l in store["identity_links"] if l["visibility"] == "public"],
    }
