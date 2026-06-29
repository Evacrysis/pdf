import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, Download, FileText, PlugZap, UploadCloud } from "lucide-react";
import "./styles.css";

const apiBase = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

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
  const [file, setFile] = useState<File | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [targetLanguage, setTargetLanguage] = useState("ja");
  const [provider, setProvider] = useState("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [model, setModel] = useState("gpt-4.1-mini");
  const [apiKey, setApiKey] = useState("");
  const [strictMode, setStrictMode] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [apiTest, setApiTest] = useState<ApiTestResult | null>(null);
  const [error, setError] = useState("");

  const hardFailureCount = useMemo(
    () => job?.pages.reduce((sum, page) => sum + page.failures.length, 0) ?? 0,
    [job],
  );
  const requiresApiTest = provider !== "dry_run" && apiTest?.ok !== true;

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

  useEffect(() => {
    setApiTest(null);
  }, [provider, baseUrl, model, apiKey]);

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
        provider,
        base_url: baseUrl,
        model,
        api_key: apiKey,
      }),
    });
    setTestBusy(false);
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    setApiTest(await response.json());
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

          <label>
            模型提供方
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="openai_compatible">OpenAI-compatible</option>
              <option value="anthropic_compatible">Anthropic-compatible</option>
              <option value="dry_run">Dry run</option>
            </select>
          </label>

          <label>
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label>
            模型
            <input value={model} onChange={(event) => setModel(event.target.value)} />
          </label>
          <label>
            API Key
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
          </label>
          <button className="secondaryButton" disabled={testBusy} type="button" onClick={testApiConnection}>
            <PlugZap size={18} />
            {testBusy ? "测试中" : "测试 API"}
          </button>
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
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
