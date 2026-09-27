# 后端镜像：Python 3.12 slim + 中文字体
# 精简依赖策略见 requirements.txt；本镜像构建关键：
#   1. 先单装 torch CPU wheel（避开默认 CUDA 2GB+，2C4G 必 OOM）
#   2. 主体依赖分批 pip install（每批 ~80-150MB），错峰编译不会同时撑爆内存
#   3. apt 也精简（不再装 libgomp1：python:3.12-slim 已带 libgomp-11）

# 中文字体：wqy-microhei.ttc 已随项目放在 backend/assets/fonts/（5MB，
# pdf_service._font 最高优先读取）—— 不再 apt 安装 fonts-wqy-microhei，
# 之前 apt 走国外源 4KB/s 花了 24 分钟，是构建慢的大头。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    HF_HOME=/data/hf-cache \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Step 1: 离线装 torch CPU 版（wheel 已由开发者本机预下载进项目 wheels/，
# 约 187MB——pytorch.org 国内访问不稳定实测 534s 超时，离线绕开）
# 注意绝不能用国内 PyPI 源装 torch：linux wheel 是 CUDA 版，会拖 553MB
# cudnn + 170MB cusparselt 等 nvidia 依赖，2C4G 直接装爆
COPY wheels ./wheels
RUN pip install --no-cache-dir wheels/torch-*.whl && rm -rf wheels

# Step 2: 装轻量 deps（fastapi/sqlalchemy/langgraph 等 < 50MB）
# ⚠️ 与 requirements.txt 保持同步（W11 Day3 实战踩坑：清单漏了
#    pydantic-settings/alembic，本地 venv 装过所以没暴露，云端镜像
#    ModuleNotFoundError 起不来——改依赖两处都要动）
RUN pip install --no-cache-dir \
        fastapi 'uvicorn[standard]' python-multipart sqlalchemy pydantic \
        pydantic-settings alembic python-dotenv \
        langgraph langgraph-checkpoint-sqlite openai \
        -i https://mirrors.aliyun.com/pypi/simple/

# Step 3: 装文档解析（pypdf / python-docx / reportlab，中等）
RUN pip install --no-cache-dir \
        pypdf python-docx reportlab \
        -i https://mirrors.aliyun.com/pypi/simple/

# Step 4: 装 Embedding 模型（sentence-transformers + transformers + tokenizers
# + scikit-learn + scipy + numpy，总计约 300MB，单独一批避免与向量库同时编译）
RUN pip install --no-cache-dir \
        'sentence-transformers>=3.0.0' scikit-learn 'numpy>=1.24.0' \
        -i https://mirrors.aliyun.com/pypi/simple/

# Step 5: 装文本切分（轻量）
RUN pip install --no-cache-dir \
        langchain-text-splitters \
        -i https://mirrors.aliyun.com/pypi/simple/

# Step 6: OCR（rapidocr 会复用前面已经装好的 numpy）
RUN pip install --no-cache-dir \
        rapidocr-onnxruntime opencv-python-headless \
        -i https://mirrors.aliyun.com/pypi/simple/

COPY app ./app
# scripts/（种子案例等运维脚本）：容器内跑 seed_cases.py 需要
COPY scripts ./scripts
# alembic 迁移（W11 Day3 实战踩坑：漏 COPY 导致容器内 alembic upgrade head
# 报 No 'script_location' key found——deploy_v2 第 6 步迁移靠它）
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN mkdir -p data

EXPOSE 8000
# 单 worker：SQLite 单写者 + 项目锁（get_project_lock）假设单进程
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]