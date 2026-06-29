# PDF Translation Workbench

严格规则驱动的 PDF 翻译工作台，用于将 PDF 按页、按行翻译成可编辑 PDF，并在输出前执行硬性 QA 门禁。

## 目标

- 前端上传 PDF，选择源语言/目标语言，配置 OpenAI-compatible 模型。
- 后端按页提取 PDF 文本、字号、位置和保护 token。
- 译文输出为真实可编辑 PDF 文本层，不整页栅格化。
- 严格执行规则：不缩放文字、不漏翻、不叠写、不裁切图片/线条、不重画保护符号。
- 每页生成 QA 报告；严格模式下硬门禁失败时任务直接失败。

## 快速启动

```bash
cp .env.example .env
docker compose up --build
```

前端: <http://localhost:5173>

后端 API: <http://localhost:8000/docs>

## 字体

日文输出必须使用规则指定字体。将字体放入 `fonts/`，或在 `.env` 中配置宿主机字体路径并挂载到容器。

默认期望:

```text
/app/fonts/SourceHanSansJP-Regular.otf
```

本机可使用现有 skill 字体:

```text
/Users/a123/work/skills/japanese-window-covering-localization/日本字体新/SourceHanSansJP-Regular.otf
```

## 工作流

1. 上传 PDF。
2. 后端为每页提取文本行、字体、字号、位置、图片/绘图区域和保护 token。
3. 每行/语义块调用模型翻译，模型只能翻译文本，不决定字号缩放和图标替代。
4. 生成可编辑 PDF。
5. 对最终 PDF 执行逐页逐行 QA。
6. 严格模式下，任何硬门禁失败都会阻止任务通过。

详细规则见 [docs/rules/pairing_manual_workflow_rules.md](docs/rules/pairing_manual_workflow_rules.md)。

## API

- `POST /api/jobs` 上传并启动翻译任务。
- `GET /api/jobs/{job_id}` 查询任务状态和逐页 QA。
- `GET /api/jobs/{job_id}/download` 下载生成 PDF。
- `GET /api/rules` 查看内置规则摘要。

## 本地开发

后端:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端:

```bash
cd frontend
npm install
npm run dev
```

测试:

```bash
cd backend
pytest
```

