"""维度层级合并业务规则：把部门批量导入的成员归属合并成单一维度层级索引。

背景：既有维度层级索引在同一成员被两个部门写入时保留了两条父路径，下游汇总
按成员计数会沿重复路径累计。这里的加工步骤是：读取既有层级索引与批量选择的
导入记录，按父子路径合并重复维度成员，为每个成员只保留一条有效父路径，并重
建单一维度层级索引（一个索引版本内确定全部成员父子关系）。

一致性约定（列表错位 / 详情残留同根因）：
- 合并结果只写一份，列表与详情都读同一份存储，不做二次拼装，避免错位；
- 重建索引时先整体移除受影响维度的旧版本行再写入新版本，不留上一版残留；
- 重复提交（同一策略 + 同一组输入记录）命中请求指纹，直接返回既有有效结果。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

IMPORT_MODULE = "dimension_import"
MERGE_MODULE = "dimension_merge"
HIERARCHY_MODULE = "dimension_hierarchy"

IMPORT_FIELDS = ["导入批次", "维度编号", "维度名称", "成员编码", "成员名称", "父路径", "来源部门", "导入时间"]
IMPORT_REQUIRED = ["导入批次", "维度编号", "成员编码", "成员名称", "父路径", "来源部门"]
STRATEGIES = ["按导入落库先后", "按父路径深度"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path_depth(path: str) -> int:
    """父路径深度：按 / 分段，空路径深度为 0。"""
    return len([seg for seg in str(path or "").split("/") if seg.strip()])


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


class DimensionHierarchyService:
    # ---------------------------------------------------------------- 来源明细
    def list_imports(
        self,
        *,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 200,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(IMPORT_MODULE))
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def create_imports(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """部门维度批量导入：逐条校验落库，逐条返回成功失败。"""
        rows = store.rows(IMPORT_MODULE)
        results: list[dict[str, Any]] = []
        created: list[dict[str, Any]] = []
        for index, values in enumerate(records, start=1):
            missing = [field for field in IMPORT_REQUIRED if not str(values.get(field) or "").strip()]
            if missing:
                results.append({"序号": index, "ok": False, "message": f"缺少必填字段：{'、'.join(missing)}"})
                continue
            entry = {"id": _next_id(rows)}
            entry.update({field: str(values.get(field, "")).strip() for field in IMPORT_FIELDS})
            entry.setdefault("维度名称", str(values.get("维度名称") or ""))
            entry["导入时间"] = entry["导入时间"] or _now()
            entry["status"] = "待合并"
            entry["pending"] = True
            entry["abnormal"] = False
            entry["失败原因"] = ""
            rows.append(entry)
            created.append(entry)
            results.append({"序号": index, "ok": True, "message": "导入记录已落库", "id": entry["id"]})
        ok_count = sum(1 for item in results if item["ok"])
        return {
            "ok": ok_count == len(results),
            "message": f"批量导入完成：成功 {ok_count} 条，失败 {len(results) - ok_count} 条",
            "逐条结果": results,
            "entries": created,
        }

    # ---------------------------------------------------------------- 批次合并
    def create_merge(self, *, import_ids: list[int], strategy: str) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """批量选择多条导入记录生成维度批次合并结果，逐条返回成功失败。

        返回 (合并结果, 提示信息, 逐条结果)；无法生成时合并结果为 None。
        """
        if strategy not in STRATEGIES:
            return None, f"合并策略「{strategy}」不在允许范围：{'、'.join(STRATEGIES)}", []
        unique_ids = sorted({int(item) for item in import_ids})
        if not unique_ids:
            return None, "请先批量选择至少一条部门维度批量导入记录", []

        # 重复提交只保留一份有效结果：同一策略 + 同一组输入记录命中请求指纹。
        fingerprint = f"{strategy}|{','.join(str(item) for item in unique_ids)}"
        for existed in store.rows(MERGE_MODULE):
            if existed.get("请求指纹") == fingerprint and existed.get("status") == "已生效":
                existed["重复提交"] = True
                return existed, "重复提交：已命中同策略同输入的既有有效合并结果，未重复写入", list(existed.get("逐条结果", []))

        imports = store.rows(IMPORT_MODULE)
        by_id = {int(row.get("id", 0)): row for row in imports}
        per_record: list[dict[str, Any]] = []
        valid_records: list[dict[str, Any]] = []
        for import_id in unique_ids:
            row = by_id.get(import_id)
            if row is None:
                per_record.append({"import_id": import_id, "ok": False, "message": "导入记录不存在或已归档"})
                continue
            if not str(row.get("成员编码") or "").strip():
                per_record.append({"import_id": import_id, "ok": False, "message": "缺少成员编码，无法参与合并"})
                continue
            if not str(row.get("父路径") or "").strip():
                per_record.append({"import_id": import_id, "ok": False, "message": "缺少父路径，无法参与合并"})
                continue
            per_record.append({"import_id": import_id, "ok": True, "message": "已纳入本次合并"})
            valid_records.append(row)
        if not valid_records:
            return None, "所选导入记录均不可用，未生成维度批次合并结果", per_record

        dimension_codes = sorted({str(row.get("维度编号", "")) for row in valid_records})
        # 第一步：读取既有数据（当前层级索引中受影响维度的有效行）。
        existing_rows = [
            row for row in store.rows(HIERARCHY_MODULE)
            if row.get("维度编号") in dimension_codes and row.get("status") == "有效"
        ]
        # 第二步：收集候选父路径——既有索引行 + 本次选中的导入记录。
        candidates: dict[str, dict[str, Any]] = {}
        for row in existing_rows:
            self._add_candidate(candidates, row, source_kind="既有索引", landed=str(row.get("落库时间", "")), ref_id=int(row.get("id", 0)))
        for row in valid_records:
            self._add_candidate(candidates, row, source_kind="批量导入", landed=str(row.get("导入时间", "")), ref_id=int(row.get("id", 0)))
        # 第三步：按父子路径合并重复维度成员，每个成员只保留一条有效父路径。
        decisions = [
            self._decide(member_key, bucket, strategy)
            for member_key, bucket in sorted(candidates.items())
        ]
        # 第四步：重建单一维度层级索引——先移除受影响维度的旧版本行，再整体写入新版本，
        # 成员父子关系在一个索引版本内全部确定，旧版本不留残留。
        hierarchy = store.rows(HIERARCHY_MODULE)
        version_no = max((self._version_no(row.get("索引版本")) for row in hierarchy), default=0) + 1
        next_version = f"V{version_no}"
        merge_no = f"MRG-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        hierarchy[:] = [row for row in hierarchy if row.get("维度编号") not in dimension_codes]
        now = _now()
        for decision in decisions:
            chosen = decision["选定候选"]
            hierarchy.append({
                "id": _next_id(hierarchy),
                "status": "有效",
                "pending": False,
                "abnormal": False,
                "索引版本": next_version,
                "维度编号": decision["维度编号"],
                "维度名称": decision["维度名称"],
                "成员编码": decision["成员编码"],
                "成员名称": decision["成员名称"],
                "父路径": chosen["父路径"],
                "路径深度": _path_depth(chosen["父路径"]),
                "来源部门": chosen["来源部门"],
                "来源记录": chosen["来源记录"],
                "落库时间": now,
                "合并批次": merge_no,
            })
        # 第五步：回写导入记录状态，保留合并结果的来源输入。
        failed_ids = {item["import_id"] for item in per_record if not item["ok"]}
        for row in valid_records:
            row["status"] = "已合并"
            row["pending"] = False
        for import_id in failed_ids:
            row = by_id.get(import_id)
            if row is not None:
                row["status"] = "合并失败"
                row["abnormal"] = True
                row["失败原因"] = next(item["message"] for item in per_record if item["import_id"] == import_id)
        conflict_count = sum(1 for item in decisions if item["是否冲突"])
        merge = {
            "id": _next_id(store.rows(MERGE_MODULE)),
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "合并批次": merge_no,
            "维度编号": "、".join(dimension_codes),
            "合并策略": strategy,
            "请求指纹": fingerprint,
            "重复提交": False,
            "输入记录数": len(unique_ids),
            "成功记录数": len(valid_records),
            "失败记录数": len(unique_ids) - len(valid_records),
            "成员数": len(decisions),
            "冲突成员数": conflict_count,
            "索引版本": next_version,
            "来源输入": [
                {"import_id": int(row.get("id", 0)), "导入批次": row.get("导入批次", ""), "来源部门": row.get("来源部门", ""),
                 "成员编码": row.get("成员编码", ""), "成员名称": row.get("成员名称", ""), "父路径": row.get("父路径", "")}
                for row in valid_records
            ],
            "逐条结果": per_record,
            "成员合并明细": [
                {key: value for key, value in decision.items() if key != "选定候选"}
                for decision in decisions
            ],
            "创建时间": now,
        }
        store.rows(MERGE_MODULE).append(merge)
        message = (
            f"维度批次合并结果已生成：{merge_no}，索引版本 {next_version}，"
            f"成员 {len(decisions)} 个（冲突 {conflict_count} 个），"
            f"成功 {len(valid_records)} 条、失败 {len(unique_ids) - len(valid_records)} 条"
        )
        return merge, message, per_record

    def _add_candidate(
        self,
        candidates: dict[str, dict[str, Any]],
        row: dict[str, Any],
        *,
        source_kind: str,
        landed: str,
        ref_id: int,
    ) -> None:
        member_code = str(row.get("成员编码", "")).strip()
        if not member_code:
            return
        key = f"{row.get('维度编号', '')}|{member_code}"
        bucket = candidates.setdefault(key, {
            "维度编号": str(row.get("维度编号", "")),
            "维度名称": str(row.get("维度名称", "")),
            "成员编码": member_code,
            "成员名称": str(row.get("成员名称", "")),
            "候选": [],
        })
        path = str(row.get("父路径", ""))
        department = str(row.get("来源部门", ""))
        for existed in bucket["候选"]:
            if existed["父路径"] == path and existed["来源部门"] == department:
                # 同部门同路径的重复候选（既有索引与批量导入重叠）：合并为一条，
                # 保留最早落库时间，来源类型合并标注，避免合并过程里同一路径重复出现。
                if landed < existed["落库时间"]:
                    existed["落库时间"] = landed
                    existed["记录id"] = ref_id
                if existed["来源类型"] != source_kind:
                    existed["来源类型"] = "既有索引+批量导入"
                return
        bucket["候选"].append({
            "父路径": path,
            "路径深度": _path_depth(path),
            "来源部门": department,
            "来源记录": f"{row.get('导入批次', row.get('合并批次', ''))}#{ref_id}",
            "来源类型": source_kind,
            "落库时间": landed,
            "记录id": ref_id,
        })

    def _decide(self, member_key: str, bucket: dict[str, Any], strategy: str) -> dict[str, Any]:
        """为同一成员的多个候选父路径选定唯一有效路径（两种冲突处理范围）。"""
        pool = bucket["候选"]
        if strategy == "按父路径深度":
            # 父路径更深（归属更具体）的优先；并列时先落库的优先。
            ordered = sorted(pool, key=lambda item: (-item["路径深度"], item["落库时间"], item["记录id"]))
            rule = "候选父路径中路径深度最深者保留"
        else:
            # 按导入落库先后：先落库的优先。
            ordered = sorted(pool, key=lambda item: (item["落库时间"], item["记录id"]))
            rule = "候选父路径中落库时间最早者保留"
        chosen = ordered[0]
        distinct_paths = {item["父路径"] for item in pool}
        conflict = len(distinct_paths) > 1
        discarded = [item for item in ordered[1:] if item["父路径"] != chosen["父路径"]]
        decision = {
            "维度编号": bucket["维度编号"],
            "维度名称": bucket["维度名称"],
            "成员编码": bucket["成员编码"],
            "成员名称": bucket["成员名称"],
            "候选父路径": [
                {"父路径": item["父路径"], "来源部门": item["来源部门"], "来源类型": item["来源类型"],
                 "落库时间": item["落库时间"], "路径深度": item["路径深度"]}
                for item in pool
            ],
            "选定父路径": chosen["父路径"],
            "是否冲突": conflict,
            "取舍说明": (
                f"{rule}：保留「{chosen['父路径']}」（{chosen['来源部门']}），"
                f"废弃 {len(discarded)} 条重复路径" if conflict else "仅一条候选父路径，直接保留"
            ),
            "选定候选": chosen,
        }
        return decision

    @staticmethod
    def _version_no(version: Any) -> int:
        text = str(version or "").lstrip("Vv")
        return int(text) if text.isdigit() else 0

    # ---------------------------------------------------------------- 结果读取
    def list_merges(self, *, page: int = 1, size: int = 200) -> tuple[list[dict[str, Any]], int]:
        """合并结果列表：与详情读同一份存储，只裁剪字段，不二次拼装，避免错位。"""
        rows = list(store.rows(MERGE_MODULE))
        total = len(rows)
        start = (page - 1) * size
        summaries = []
        for row in rows[start:start + size]:
            summaries.append({key: value for key, value in row.items() if key not in ("成员合并明细", "逐条结果", "来源输入", "请求指纹")})
        return summaries, total

    def get_merge(self, merge_id: int) -> dict[str, Any] | None:
        return store.find(MERGE_MODULE, merge_id)

    # ---------------------------------------------------------------- 层级索引
    def current_hierarchy(self, *, dimension_code: str | None = None) -> dict[str, Any]:
        """交付数据：单一维度层级索引。同一成员在当前版本只保留一条有效父路径。"""
        rows = [row for row in store.rows(HIERARCHY_MODULE) if row.get("status") == "有效"]
        if dimension_code:
            rows = [row for row in rows if row.get("维度编号") == dimension_code]
        versions = sorted({str(row.get("索引版本", "")) for row in rows})
        return {"索引版本": versions[-1] if versions else "", "items": rows, "total": len(rows)}

    def hierarchy_summary(self, *, dimension_code: str | None = None) -> dict[str, Any]:
        """下游汇总核对：按成员计数，验证同一成员只保留一条有效父路径、汇总不重复。"""
        current = self.current_hierarchy(dimension_code=dimension_code)
        rows = current["items"]
        by_member: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_member.setdefault(str(row.get("成员编码", "")), []).append(row)
        duplicated = [
            {
                "成员编码": code,
                "成员名称": group[0].get("成员名称", ""),
                "出现次数": len(group),
                "父路径列表": [str(item.get("父路径", "")) for item in group],
            }
            for code, group in sorted(by_member.items())
            if len(group) > 1
        ]
        by_parent: dict[str, int] = {}
        for row in rows:
            parent = str(row.get("父路径", ""))
            by_parent[parent] = by_parent.get(parent, 0) + 1
        ok = not duplicated
        return {
            "维度编号": dimension_code or "全部",
            "索引版本": current["索引版本"],
            "索引行数": len(rows),
            "去重成员数": len(by_member),
            "重复成员数": len(duplicated),
            "重复成员": duplicated,
            "按父级汇总": [{"父路径": path, "成员数": count} for path, count in sorted(by_parent.items())],
            "核对结论": (
                "通过：同一成员只保留一条有效父路径，下游汇总按成员计数不重复"
                if ok else
                f"不通过：{len(duplicated)} 个成员仍保留多条父路径，下游汇总会重复累计"
            ),
        }
