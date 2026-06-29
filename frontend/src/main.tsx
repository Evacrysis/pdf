import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, Download, FileText, PlugZap, UploadCloud } from "lucide-react";
import "./styles.css";

const apiBase = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const modelConfigStorageKey = "pdf-translation-model-config";

type StoredModelConfig = {
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  testedFingerprint?: string;
};

const defaultModelConfig: StoredModelConfig = {
  provider: "openai_compatible",
  baseUrl: "https://api.openai.com/v1",
  model: "gpt-4.1-mini",
  apiKey: "",
};

function modelFingerprint(provider: string, baseUrl: string, model: string, apiKey: string): string {
  return JSON.stringify({ provider, baseUrl, model, apiKey });
}

function readStoredModelConfig(): StoredModelConfig {
  try {
    const raw = window.localStorage.getItem(modelConfigStorageKey);
    if (!raw) return defaultModelConfig;
    return { ...defaultModelConfig, ...JSON.parse(raw) };
  } catch {
    return defaultModelConfig;
  }
}

const stageLabels: Record<string, string> = {
  queued: "排队中",
  extracting: "解析原文",
  translating: "翻译中",
  writing_pdf: "生成 PDF",
  qa: "规则校验",
  completed: "已完成",
  qa_failed: "校验失败",
  failed: "失败",
};

type Gate = {
  code: string;
  severity: "info" | "warning" | "hard_fail";
  passed: boolean;
  message: string;
  page_index?: number;
  line_index?: number;
  details?: Record<string, unknown>;
};

type PageReport = {
  page_index: number;
  status: string;
  line_count: number;
  failures: Gate[];
  warnings: Gate[];
};

type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  source_filename: string;
  output_path?: string | null;
  stage: string;
  progress: number;
  total_pages: number;
  processed_pages: number;
  total_lines: number;
  processed_lines: number;
  pages: PageReport[];
  errors: string[];
};

type ApiTestResult = {
  ok: boolean;
  provider: string;
  normalized_base_url?: string;
  message: string;
  model?: string;
  model_found?: boolean;
  sample_models: string[];
};

function App() {
  const storedModelConfig = useMemo(() => readStoredModelConfig(), []);
  const [file, setFile] = useState<File | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [targetLanguage, setTargetLanguage] = useState("ja");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [provider, setProvider] = useState(storedModelConfig.provider);
  const [baseUrl, setBaseUrl] = useState(storedModelConfig.baseUrl);
  const [model, setModel] = useState(storedModelConfig.model);
  const [apiKey, setApiKey] = useState(storedModelConfig.apiKey);
  const [draftProvider, setDraftProvider] = useState(storedModelConfig.provider);
  const [draftBaseUrl, setDraftBaseUrl] = useState(storedModelConfig.baseUrl);
  const [draftModel, setDraftModel] = useState(storedModelConfig.model);
  const [draftApiKey, setDraftApiKey] = useState(storedModelConfig.apiKey);
  const [modelConfigOpen, setModelConfigOpen] = useState(false);
  const [testedFingerprint, setTestedFingerprint] = useState(storedModelConfig.testedFingerprint ?? "");
  const [draftTestedFingerprint, setDraftTestedFingerprint] = useState(storedModelConfig.testedFingerprint ?? "");
  const [strictMode, setStrictMode] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [apiTest, setApiTest] = useState<ApiTestResult | null>(null);
  const [error, setError] = useState("");
  const sourcePreviewRef = useRef<HTMLDivElement | null>(null);
  const translatedPreviewRef = useRef<HTMLDivElement | null>(null);
  const syncingPreviewRef = useRef(false);

  const hardFailureCount = useMemo(
    () => job?.pages.reduce((sum, page) => sum + page.failures.length, 0) ?? 0,
    [job],
  );
  const activeFingerprint = modelFingerprint(provider, baseUrl, model, apiKey);
  const draftFingerprint = modelFingerprint(draftProvider, draftBaseUrl, draftModel, draftApiKey);
  const requiresApiTest = provider !== "dry_run" && testedFingerprint !== activeFingerprint;
  const progressPercent = Math.round(Math.max(0, Math.min(1, job?.progress ?? 0)) * 100);
  const canPreview = Boolean(job?.id && job?.output_path && (job?.total_pages ?? 0) > 0);
  const previewPages = useMemo(
    () => Array.from({ length: job?.total_pages ?? 0 }, (_, index) => index),
    [job?.total_pages],
  );

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`${apiBase}/api/jobs/${job.id}`);
      if (response.ok) {
        setJob(await response.json());
      }
    }, 1600);
    return () => window.clearInterval(timer);
  }, [job]);

  function openModelConfig() {
    setDraftProvider(provider);
    setDraftBaseUrl(baseUrl);
    setDraftModel(model);
    setDraftApiKey(apiKey);
    setDraftTestedFingerprint(testedFingerprint);
    setModelConfigOpen(true);
  }

  function updateDraft(updater: () => void) {
    updater();
    setApiTest(null);
    setDraftTestedFingerprint("");
  }

  function saveModelConfig() {
    setProvider(draftProvider);
    setBaseUrl(draftBaseUrl);
    setModel(draftModel);
    setApiKey(draftApiKey);
    const savedTestedFingerprint = draftTestedFingerprint === draftFingerprint ? draftTestedFingerprint : "";
    setTestedFingerprint(savedTestedFingerprint);
    window.localStorage.setItem(
      modelConfigStorageKey,
      JSON.stringify({
        provider: draftProvider,
        baseUrl: draftBaseUrl,
        model: draftModel,
        apiKey: draftApiKey,
        testedFingerprint: savedTestedFingerprint,
      }),
    );
    setModelConfigOpen(false);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("请选择 PDF 文件。");
      return;
    }
    if (requiresApiTest) {
      setError("请先点击“测试 API”，并确认连接正常后再开始翻译。");
      return;
    }
    const startPage = pageStart.trim();
    const endPage = pageEnd.trim();
    if ((startPage && Number(startPage) < 1) || (endPage && Number(endPage) < 1)) {
      setError("页码范围必须使用从 1 开始的正整数。");
      return;
    }
    if (startPage && endPage && Number(startPage) > Number(endPage)) {
      setError("起始页不能大于结束页。");
      return;
    }
    setBusy(true);
    setError("");
    const data = new FormData();
    data.append("file", file);
    data.append("source_language", sourceLanguage);
    data.append("target_language", targetLanguage);
    data.append("provider", provider);
    data.append("base_url", baseUrl);
    data.append("model", model);
    data.append("api_key", apiKey);
    data.append("strict_mode", String(strictMode));
    if (startPage) data.append("page_start", startPage);
    if (endPage) data.append("page_end", endPage);
    const response = await fetch(`${apiBase}/api/jobs`, { method: "POST", body: data });
    setBusy(false);
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    setJob(await response.json());
  }

  async function testApiConnection() {
    setTestBusy(true);
    setApiTest(null);
    setError("");
    const response = await fetch(`${apiBase}/api/model/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: draftProvider,
        base_url: draftBaseUrl,
        model: draftModel,
        api_key: draftApiKey,
      }),
    });
    setTestBusy(false);
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    const result = await response.json();
    setApiTest(result);
    if (result.ok) {
      setDraftTestedFingerprint(draftFingerprint);
    }
  }

  function syncPreviewScroll(source: "source" | "translated") {
    if (syncingPreviewRef.current) return;
    const from = source === "source" ? sourcePreviewRef.current : translatedPreviewRef.current;
    const to = source === "source" ? translatedPreviewRef.current : sourcePreviewRef.current;
    if (!from || !to) return;
    syncingPreviewRef.current = true;
    to.scrollTop = from.scrollTop;
    to.scrollLeft = from.scrollLeft;
    window.requestAnimationFrame(() => {
      syncingPreviewRef.current = false;
    });
  }

  return (
    <main className="appShell">
      <section className="toolbar">
        <div>
          <h1>PDF Translation Workbench</h1>
          <p>源 PDF 驱动翻译，逐页逐行校验，硬门禁失败不放行。</p>
        </div>
        <a className="rulesLink" href={`${apiBase}/api/rules`} target="_blank" rel="noreferrer">
          查看规则
        </a>
      </section>

      <section className="layout">
        <form className="panel" onSubmit={submit}>
          <h2>任务配置</h2>
          <label className="dropZone">
            <UploadCloud size={28} />
            <span>{file ? file.name : "上传 PDF"}</span>
            <input type="file" accept="application/pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>

          <div className="grid2">
            <label>
              源语言
              <select value={sourceLanguage} onChange={(event) => setSourceLanguage(event.target.value)}>
                <option value="en">English</option>
                <option value="zh">中文</option>
                <option value="ja">日本語</option>
              </select>
            </label>
            <label>
              目标语言
              <select value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value)}>
                <option value="ja">日本語</option>
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </label>
          </div>

          <div className="grid2">
            <label>
              起始页
              <input
                min="1"
                placeholder="默认第 1 页"
                type="number"
                value={pageStart}
                onChange={(event) => setPageStart(event.target.value)}
              />
            </label>
            <label>
              结束页
              <input
                min="1"
                placeholder="默认最后一页"
                type="number"
                value={pageEnd}
                onChange={(event) => setPageEnd(event.target.value)}
              />
            </label>
          </div>

          <div className="modelConfigSummary">
            <div>
              <span>模型配置</span>
              <strong>{provider === "dry_run" ? "Dry run" : model}</strong>
              <small>{provider === "dry_run" ? "本地模拟翻译" : `${provider} / ${baseUrl}`}</small>
            </div>
            <button className="secondaryButton" type="button" onClick={openModelConfig}>
              <PlugZap size={18} />
              配置模型
            </button>
          </div>
          {apiTest && (
            <div className={apiTest.ok ? "apiTestResult ok" : "apiTestResult bad"}>
              <strong>{apiTest.ok ? "连接正常" : "连接失败"}</strong>
              <span>{apiTest.message}</span>
              {apiTest.normalized_base_url && <span>规范化地址：{apiTest.normalized_base_url}</span>}
              {apiTest.sample_models.length > 0 && (
                <span>模型示例：{apiTest.sample_models.slice(0, 5).join("、")}</span>
              )}
            </div>
          )}
          <label className="checkRow">
            <input type="checkbox" checked={strictMode} onChange={(event) => setStrictMode(event.target.checked)} />
            严格模式：硬门禁失败则任务失败
          </label>

          <button disabled={busy || requiresApiTest} type="submit">
            <FileText size={18} />
            {busy ? "提交中" : requiresApiTest ? "先测试 API" : "开始翻译"}
          </button>
          {error && <p className="errorText">{error}</p>}
        </form>

        <section className="panel reportPanel">
          <div className="reportHeader">
            <div>
              <h2>逐页 QA</h2>
              <p>{job ? `${job.source_filename} / ${job.status}` : "等待任务"}</p>
            </div>
            {job?.status === "completed" && (
              <a className="download" href={`${apiBase}/api/jobs/${job.id}/download`}>
                <Download size={18} />
                下载 PDF
              </a>
            )}
          </div>

          {job && (
            <div className={hardFailureCount > 0 ? "status failed" : "status passed"}>
              {hardFailureCount > 0 ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
              <span>硬门禁失败 {hardFailureCount} 项</span>
            </div>
          )}

          {job && (
            <div className="progressBlock">
              <div className="progressMeta">
                <span>{stageLabels[job.stage] ?? job.stage}</span>
                <span>{progressPercent}%</span>
              </div>
              <div className="progressTrack" aria-label="翻译进度">
                <div className="progressFill" style={{ width: `${progressPercent}%` }} />
              </div>
              <p>
                已处理 {job.processed_lines}/{job.total_lines || 0} 行，
                {job.processed_pages}/{job.total_pages || 0} 页
              </p>
            </div>
          )}

          {job?.errors?.map((item) => (
            <p className="errorText" key={item}>{item}</p>
          ))}

          <div className="pageList">
            {job?.pages.map((page) => (
              <article className="pageItem" key={page.page_index}>
                <div>
                  <strong>第 {page.page_index + 1} 页</strong>
                  <span>{page.line_count} 行</span>
                </div>
                <span className={page.status === "passed" ? "badge pass" : "badge fail"}>{page.status}</span>
                {page.failures.map((failure) => (
                  <p className="failure" key={`${failure.code}-${failure.line_index}`}>
                    {failure.code}: {failure.message}
                  </p>
                ))}
              </article>
            ))}
          </div>

          {canPreview && (
            <section className="previewSection">
              <div className="previewTitle">
                <h2>原文 / 译文同步预览</h2>
                <p>左右拖动条同步，按最终生成 PDF 渲染。</p>
              </div>
              <div className="previewGrid">
                <div className="previewPane">
                  <div className="previewPaneHeader">原文</div>
                  <div
                    className="previewScroller"
                    ref={sourcePreviewRef}
                    onScroll={() => syncPreviewScroll("source")}
                  >
                    {previewPages.map((pageIndex) => (
                      <figure className="previewPage" key={`source-${pageIndex}`}>
                        <figcaption>第 {pageIndex + 1} 页</figcaption>
                        <img
                          src={`${apiBase}/api/jobs/${job!.id}/preview/source/${pageIndex}`}
                          alt={`原文第 ${pageIndex + 1} 页`}
                          loading="lazy"
                        />
                      </figure>
                    ))}
                  </div>
                </div>
                <div className="previewPane">
                  <div className="previewPaneHeader">译文</div>
                  <div
                    className="previewScroller"
                    ref={translatedPreviewRef}
                    onScroll={() => syncPreviewScroll("translated")}
                  >
                    {previewPages.map((pageIndex) => (
                      <figure className="previewPage" key={`translated-${pageIndex}`}>
                        <figcaption>第 {pageIndex + 1} 页</figcaption>
                        <img
                          src={`${apiBase}/api/jobs/${job!.id}/preview/translated/${pageIndex}`}
                          alt={`译文第 ${pageIndex + 1} 页`}
                          loading="lazy"
                        />
                      </figure>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}
        </section>
      </section>

      {modelConfigOpen && (
        <div className="modalBackdrop" role="presentation">
          <section className="modalPanel" role="dialog" aria-modal="true" aria-labelledby="model-config-title">
            <div className="modalHeader">
              <h2 id="model-config-title">模型配置</h2>
              <button className="iconButton" type="button" onClick={() => setModelConfigOpen(false)}>
                关闭
              </button>
            </div>

            <label>
              模型提供方
              <select
                value={draftProvider}
                onChange={(event) => updateDraft(() => setDraftProvider(event.target.value))}
              >
                <option value="openai_compatible">OpenAI-compatible</option>
                <option value="anthropic_compatible">Anthropic-compatible</option>
                <option value="dry_run">Dry run</option>
              </select>
            </label>

            <label>
              Base URL
              <input value={draftBaseUrl} onChange={(event) => updateDraft(() => setDraftBaseUrl(event.target.value))} />
            </label>
            <label>
              模型
              <input value={draftModel} onChange={(event) => updateDraft(() => setDraftModel(event.target.value))} />
            </label>
            <label>
              API Key
              <input
                type="password"
                value={draftApiKey}
                onChange={(event) => updateDraft(() => setDraftApiKey(event.target.value))}
              />
            </label>

            {apiTest && (
              <div className={apiTest.ok ? "apiTestResult ok" : "apiTestResult bad"}>
                <strong>{apiTest.ok ? "连接正常" : "连接失败"}</strong>
                <span>{apiTest.message}</span>
                {apiTest.normalized_base_url && <span>规范化地址：{apiTest.normalized_base_url}</span>}
                {apiTest.sample_models.length > 0 && (
                  <span>模型示例：{apiTest.sample_models.slice(0, 5).join("、")}</span>
                )}
              </div>
            )}

            <div className="modalActions">
              <button
                className="secondaryButton"
                disabled={testBusy || draftProvider === "dry_run"}
                type="button"
                onClick={testApiConnection}
              >
                <PlugZap size={18} />
                {testBusy ? "测试中" : "测试 API"}
              </button>
              <button type="button" onClick={saveModelConfig}>
                保存配置
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
