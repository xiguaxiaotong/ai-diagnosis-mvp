"""P2 案例 API：上传（存 SQLite + Chroma）/ 列表 / 详情 / 删除。"""

import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import CASES_DIR
from app.db.database import get_db
from app.services import case_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("/upload", status_code=201)
def upload_case(
    file: UploadFile = File(...),
    title: str = Form(...),
    industry: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """上传案例文档（md/txt/docx/pdf）→ 元数据落库 + 向量化（失败不阻断）。

    P2 案例自动向量化：入库即调统一向量化入口。向量计算失败时案例照常
    入库（vectorized=False，检索暂不可见，后端记 warning 日志），运营跑
    import_cases_csv.py --backfill 补齐后即可检索。
    """
    from app.retrieval.loader import SUPPORTED_EXTS

    filename = file.filename or "unnamed.txt"
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(status_code=415,
                            detail=f"不支持的文件类型 {ext}，支持 {sorted(SUPPORTED_EXTS)}")

    CASES_DIR.mkdir(parents=True, exist_ok=True)
    save_path = CASES_DIR / f"{int(time.time() * 1000)}_{filename}"
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件内容为空")
    save_path.write_bytes(content)

    try:
        case = case_service.create_case_from_file(db, save_path, title, industry)
    except ValueError as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception:
        save_path.unlink(missing_ok=True)
        logger.exception("案例入库失败")
        raise HTTPException(status_code=500, detail="案例入库失败，详见后端日志") from None
    return {**case_service.case_to_dict(case),
            "vectorized": case.vector_id is not None}


@router.get("")
def list_cases(limit: int = 50, db: Session = Depends(get_db)):
    return {"items": [case_service.case_to_dict(c) for c in case_service.list_cases(db, limit)]}


@router.get("/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)):
    case = case_service.get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="案例不存在")
    return case_service.case_to_dict(case)


@router.delete("/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    if not case_service.delete_case(db, case_id):
        raise HTTPException(status_code=404, detail="案例不存在")
    return {"deleted": True}
