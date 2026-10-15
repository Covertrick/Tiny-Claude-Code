"""增量语义归纳（Incremental Knowledge Synthesis）

流程：
  新输入 → 提炼结构化卡片 → 向量/主题对齐检索
    ├─ 命中（≥阈值）→ LLM Merge(旧, 新) → Upsert 更新
    └─ 未命中 → 新建知识卡片

多租户：按 user_id（+ 可选 group_id）隔离。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from agent.embedding import cosine, get_embedder
from agent.knowledge.store import MemoryRecord, get_knowledge_store

# 哈希向量下 0.85 过严；fastembed 时可用 QQ_SYNTHESIS_THRESHOLD=0.85
DEFAULT_THRESHOLD = float(os.getenv("QQ_SYNTHESIS_THRESHOLD", "0.72") or "0.72")

_CARD_META = "is_card"

_EXTRACT_SYS = (
    "你是知识提炼器。把用户非结构化文本提炼成一张知识卡片 JSON，"
    "只输出合法 JSON，不要 Markdown。"
    '格式：{"topic":"主题短名","summary":"80字内中文摘要",'
    '"entities":{任意键值，如 target/skills/route/requirements/decisions}}。'
    "招聘/JD→skills+requirements；学习路线→route；会议纪要→decisions+action_items。"
)

_MERGE_SYS = (
    "你是知识合并器。把旧卡片与新提炼合并为一张最新卡片 JSON，"
    "去重、补全冲突处取更新信息，只输出合法 JSON。"
    '格式同：{"topic","summary","entities"}。'
)


@dataclass
class SynthesisResult:
    action: str  # created | merged | skipped
    card_id: str
    topic: str
    score: float
    summary: str
    message: str


def _parse_json_obj(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    # 剥代码围栏
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if m:
            text = m.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 截取首个 {...}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _heuristic_extract(text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    skills = re.findall(
        r"(?:Java|Python|Go|Rust|C\+\+|Spring(?:\s*Boot)?|Redis|MySQL|Kafka|"
        r"Kubernetes|K8s|Docker|LLM|深度学习|机器学习|前端|后端|算法)",
        text,
        re.I,
    )
    skills = list(dict.fromkeys(s.strip() for s in skills))[:20]
    entities: dict[str, Any] = {}
    if skills:
        entities["skills"] = skills
    # 稳定主题：按文档类型 + 主技能，便于跨次输入对齐
    if re.search(r"招聘|JD|岗位|工程师|任职|要求", text, re.I):
        entities["type"] = "job_requirement"
        head = skills[0] if skills else "通用"
        topic = f"招聘·{head}"
    elif re.search(r"学习路线|路线图|roadmap|课程|培养", text, re.I):
        entities["type"] = "learning_path"
        head = skills[0] if skills else "通用"
        topic = f"学习路线·{head}"
    elif re.search(r"会议|纪要|决议|待办", text, re.I):
        entities["type"] = "meeting_notes"
        topic = "会议纪要"
    else:
        topic = (lines[0] if lines else text[:40])[:48] or "未命名主题"
    return {
        "topic": topic[:48],
        "summary": (text or "")[:200].replace("\n", " "),
        "entities": entities,
    }


def _llm_json(system: str, user: str, *, max_tokens: int = 500) -> dict[str, Any] | None:
    try:
        from agent.channel.trust import wrap_untrusted
        from agent.core.llm import chat

        msg = chat(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": wrap_untrusted("knowledge_input", user, max_len=4000),
                },
            ],
            tools=None,
            max_tokens=max_tokens,
            timeout=60,
        )
        return _parse_json_obj(msg.get("content") or "")
    except Exception as e:
        print(f"[synthesis] LLM 调用失败: {e}")
        return None


def extract_structured(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"topic": "", "summary": "", "entities": {}}
    obj = _llm_json(_EXTRACT_SYS, text)
    if not obj:
        return _heuristic_extract(text)
    topic = str(obj.get("topic") or "").strip() or _heuristic_extract(text)["topic"]
    summary = str(obj.get("summary") or "").strip() or text[:200]
    entities = obj.get("entities") if isinstance(obj.get("entities"), dict) else {}
    return {"topic": topic[:80], "summary": summary[:400], "entities": entities}


def merge_structured(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"old": old, "new": new}, ensure_ascii=False)
    obj = _llm_json(_MERGE_SYS, payload, max_tokens=600)
    if not obj:
        # 启发式合并
        ents = dict(old.get("entities") or {})
        for k, v in (new.get("entities") or {}).items():
            if isinstance(v, list) and isinstance(ents.get(k), list):
                ents[k] = list(dict.fromkeys([*ents[k], *v]))[:40]
            else:
                ents[k] = v
        return {
            "topic": new.get("topic") or old.get("topic") or "",
            "summary": (new.get("summary") or old.get("summary") or "")[:400],
            "entities": ents,
        }
    topic = str(obj.get("topic") or new.get("topic") or old.get("topic") or "")[:80]
    summary = str(obj.get("summary") or "")[:400]
    entities = obj.get("entities") if isinstance(obj.get("entities"), dict) else {}
    return {"topic": topic, "summary": summary or new.get("summary", ""), "entities": entities}


def _card_embed_text(topic: str, summary: str, entities: dict | None = None) -> str:
    parts = [topic or "", summary or ""]
    if entities:
        try:
            parts.append(json.dumps(entities, ensure_ascii=False)[:500])
        except Exception:
            pass
    return " ".join(p for p in parts if p)


def _topic_boost(a: str, b: str) -> float:
    ta = set(re.findall(r"[\u4e00-\u9fff]{2}|[a-zA-Z0-9_]{2,}", (a or "").lower()))
    tb = set(re.findall(r"[\u4e00-\u9fff]{2}|[a-zA-Z0-9_]{2,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    j = inter / union
    # 子串包含再加分
    na, nb = (a or "").strip().lower(), (b or "").strip().lower()
    if na and nb and (na in nb or nb in na):
        j = max(j, 0.9)
    return j


def _is_card(rec: MemoryRecord) -> bool:
    return bool((rec.metadata or {}).get(_CARD_META)) or rec.source in (
        "synthesis",
        "synthesis_merge",
    )


def find_matching_card(
    *,
    user_id: str,
    topic: str,
    summary: str,
    group_id: str | None = None,
    threshold: float | None = None,
) -> tuple[MemoryRecord, float] | None:
    threshold = DEFAULT_THRESHOLD if threshold is None else threshold
    store = get_knowledge_store()
    emb = get_embedder()
    q = emb.embed(_card_embed_text(topic, summary))
    best: tuple[MemoryRecord, float] | None = None
    with store._lock:
        for rec, vec in zip(store._records, store._vectors):
            if str(rec.user_id) != str(user_id):
                continue
            if rec.archived:
                continue
            if not _is_card(rec):
                continue
            if group_id is not None and str(rec.group_id) != str(group_id):
                # 私聊卡片在群场景也可对齐：仅当 group_id 显式 private 时严格
                if group_id != "private" and rec.group_id != "private":
                    continue
            vec_score = cosine(q, vec)
            boost = _topic_boost(topic, rec.title or "")
            # 主题高度重合时降低对纯向量分数的依赖（哈希嵌入尤甚）
            score = max(vec_score, 0.5 * vec_score + 0.5 * boost)
            if boost >= 0.7:
                score = max(score, 0.82)
            if best is None or score > best[1]:
                best = (rec, score)
    if not best:
        return None
    # 主题强匹配：阈值放宽到 0.55
    need = min(threshold, 0.55) if _topic_boost(topic, best[0].title or "") >= 0.55 else threshold
    if best[1] >= need:
        return best
    return None


def _format_card_body(topic: str, summary: str, entities: dict[str, Any]) -> str:
    try:
        ent_s = json.dumps(entities or {}, ensure_ascii=False)
    except Exception:
        ent_s = "{}"
    return f"{summary}\n\n[entities] {ent_s}"


def upsert_knowledge(
    *,
    user_id: str,
    text: str,
    group_id: str = "private",
    threshold: float | None = None,
    use_llm: bool = True,
) -> SynthesisResult:
    """增量提炼并 Upsert 到用户知识卡片。"""
    text = (text or "").strip()
    if not text:
        return SynthesisResult("skipped", "", "", 0.0, "", "空内容，跳过。")

    structured = extract_structured(text) if use_llm else _heuristic_extract(text)
    topic = structured.get("topic") or "未命名"
    summary = structured.get("summary") or text[:200]
    entities = structured.get("entities") if isinstance(structured.get("entities"), dict) else {}

    hit = find_matching_card(
        user_id=user_id,
        topic=topic,
        summary=summary,
        group_id=None,  # 同用户跨群对齐主题
        threshold=threshold,
    )
    store = get_knowledge_store()

    if hit:
        old_rec, score = hit
        old_ents = (old_rec.metadata or {}).get("entities") or {}
        if not isinstance(old_ents, dict):
            old_ents = {}
        old_struct = {
            "topic": old_rec.title or topic,
            "summary": (old_rec.text or "").split("\n\n[entities]")[0][:400],
            "entities": old_ents,
        }
        merged = (
            merge_structured(old_struct, structured)
            if use_llm
            else {
                "topic": topic,
                "summary": summary,
                "entities": {**old_ents, **entities},
            }
        )
        new_topic = merged.get("topic") or topic
        new_summary = merged.get("summary") or summary
        new_ents = merged.get("entities") if isinstance(merged.get("entities"), dict) else entities
        body = _format_card_body(new_topic, new_summary, new_ents)
        meta = dict(old_rec.metadata or {})
        meta[_CARD_META] = True
        meta["entities"] = new_ents
        meta["version"] = int(meta.get("version") or 1) + 1
        meta["last_merge_score"] = round(score, 4)
        updated = store.update_record(
            memory_id=old_rec.id,
            user_id=user_id,
            text=body[:2000],
            title=str(new_topic)[:80],
            metadata=meta,
            source="synthesis_merge",
            layer="semantic",
            kind="fact",
        )
        cid = updated.id if updated else old_rec.id
        return SynthesisResult(
            action="merged",
            card_id=cid,
            topic=str(new_topic),
            score=score,
            summary=str(new_summary)[:200],
            message=(
                f"已合并知识卡片「{new_topic}」(id={cid}, "
                f"相似度={score:.2f}, v{meta['version']})"
            ),
        )

    body = _format_card_body(topic, summary, entities)
    rec = store.remember(
        user_id=user_id,
        group_id=group_id or "private",
        text=body[:2000],
        source="synthesis",
        kind="fact",
        title=str(topic)[:80],
        layer="semantic",
        metadata={
            _CARD_META: True,
            "entities": entities,
            "version": 1,
        },
    )
    return SynthesisResult(
        action="created",
        card_id=rec.id,
        topic=str(topic),
        score=0.0,
        summary=str(summary)[:200],
        message=f"已新建知识卡片「{topic}」(id={rec.id})",
    )


def list_knowledge_cards(*, user_id: str, limit: int = 20) -> str:
    store = get_knowledge_store()
    with store._lock:
        cards = [
            r
            for r in store._records
            if str(r.user_id) == str(user_id) and not r.archived and _is_card(r)
        ]
    cards = list(reversed(cards))[:limit]
    if not cards:
        return "还没有知识卡片。可以说「归纳一下 …」或发长文让我提炼。"
    lines = [f"知识卡片（{len(cards)}）："]
    for r in cards:
        ver = (r.metadata or {}).get("version") or 1
        summ = (r.text or "").split("\n\n[entities]")[0][:80]
        lines.append(f"- [{r.id}] v{ver} {r.title or '?'}：{summ}")
    return "\n".join(lines)


def synthesize_user_episodic(
    *, user_id: str, group_id: str = "private", limit: int = 12, min_len: int = 24
) -> int:
    """后台：把未合成的情景记忆批量拼成一次 Upsert（少烧 Token）。"""
    store = get_knowledge_store()
    with store._lock:
        pending = [
            r
            for r in store._records
            if str(r.user_id) == str(user_id)
            and not r.archived
            and r.layer == "episodic"
            and not (r.metadata or {}).get("synthesized")
            and len(r.text or "") >= min_len
            and r.source != "quick_capture"
        ][-limit:]
    if not pending:
        return 0
    blob = "\n".join(
        f"- {r.title + '：' if r.title else ''}{r.text}" for r in pending
    )
    try:
        upsert_knowledge(
            user_id=user_id,
            text=blob[:3500],
            group_id=pending[-1].group_id or group_id,
        )
    except Exception as e:
        print(f"[synthesis] episodic 批量失败: {e}")
        return 0
    for rec in pending:
        store.update_record(
            memory_id=rec.id,
            user_id=user_id,
            metadata={**(rec.metadata or {}), "synthesized": True},
        )
    return len(pending)


def looks_like_knowledge_doc(text: str) -> bool:
    """启发式：长文 + 招聘/路线/纪要等信号 → 适合自动归纳。"""
    t = (text or "").strip()
    if len(t) < 80:
        return False
    return bool(
        re.search(
            r"招聘|岗位要求|任职|JD|学习路线|路线图|roadmap|会议纪要|决议|"
            r"技能要求|必备|加分项|培养计划",
            t,
            re.I,
        )
    )
