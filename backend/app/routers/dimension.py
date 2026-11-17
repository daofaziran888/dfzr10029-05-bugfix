"""维度管理接口：维护分析维度，覆盖提交定义、发布维度、停用维度等动作。

维度层级合并子资源（来源明细 / 批次合并结果 / 单一维度层级索引）也挂在这里，
全部声明在 /{entry_id} 之前，避免被详情路由截获。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.dimension import DimensionService
from app.services.dimension_hierarchy import STRATEGIES, DimensionHierarchyService

router = APIRouter(prefix="/api/dimension", tags=["维度管理"])

service = DimensionService()
hierarchy_service = DimensionHierarchyService()

LIST_FIELDS = ["维度编号", "维度名称", "维度类型", "关联数据集", "层级结构", "默认取值", "排序规则", "维度状态"]
STATUSES = ["草稿", "已定义", "已发布", "已停用"]
IMPORT_FILTER_FIELDS = ["导入批次", "维度编号", "成员编码", "来源部门", "status"]


class MergePayload(BaseModel):
    """批量选择多条导入记录生成维度批次合并结果的请求体。"""

    import_ids: list[int] = Field(default_factory=list)
    strategy: str = STRATEGIES[0]


class ImportBatchPayload(BaseModel):
    """部门维度批量导入：一次可提交多条来源明细。"""

    records: list[dict[str, object]] = Field(default_factory=list)


# ---------------------------------------------------------------- 维度层级合并
@router.get("/imports")
def list_imports(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """部门维度批量导入记录（来源明细）：合并加工的输入。"""
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in IMPORT_FILTER_FIELDS and value.strip()
    }
    items, total = hierarchy_service.list_imports(filters=filters, page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/imports", response_model=ActionResult)
def create_imports(payload: ImportBatchPayload) -> ActionResult:
    """部门批量导入成员归属：逐条校验落库，逐条返回成功失败。"""
    if not payload.records:
        return ActionResult(ok=False, message="导入内容为空，请至少提交一条来源明细")
    result = hierarchy_service.create_imports(payload.records)
    return ActionResult(ok=bool(result["ok"]), message=str(result["message"]), entry=result)


@router.post("/merges", response_model=ActionResult)
def create_merge(payload: MergePayload) -> ActionResult:
    """编排维度批次合并结果：读既有数据后按父子路径合并重复维度成员，重建单一维度层级索引。"""
    merge, message, per_record = hierarchy_service.create_merge(
        import_ids=payload.import_ids, strategy=payload.strategy.strip())
    if merge is None:
        return ActionResult(ok=False, message=message, entry={"逐条结果": per_record})
    return ActionResult(ok=True, message=message, entry=merge)


@router.get("/merges")
def list_merges(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """维度批次合并结果列表：与详情读同一份存储，避免错位。"""
    items, total = hierarchy_service.list_merges(page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/merges/{merge_id}")
def get_merge(merge_id: int) -> dict:
    """维度批次合并结果详情：保留来源输入与成员父路径合并过程。"""
    merge = hierarchy_service.get_merge(merge_id)
    if merge is None:
        raise HTTPException(status_code=404, detail=f"维度批次合并结果 {merge_id} 不存在或已归档")
    return merge


@router.get("/hierarchy")
def current_hierarchy(dimension_code: str | None = Query(default=None)) -> dict:
    """交付数据：单一维度层级索引，同一成员只保留一条有效父路径。"""
    return hierarchy_service.current_hierarchy(dimension_code=dimension_code)


@router.get("/hierarchy/summary")
def hierarchy_summary(dimension_code: str | None = Query(default=None)) -> dict:
    """下游汇总核对：按成员计数不重复，作为消费结果的验证口径。"""
    return hierarchy_service.hierarchy_summary(dimension_code=dimension_code)


# ---------------------------------------------------------------- 维度管理 CRUD


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按维度编号检索"),
    status: str | None = Query(default=None, description="草稿、已定义、已发布、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、维度编号关键字与状态过滤维度管理列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dimension.csv"'})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条分析维度明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"分析维度 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条分析维度，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="分析维度已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条分析维度执行提交定义、发布维度、停用维度；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
