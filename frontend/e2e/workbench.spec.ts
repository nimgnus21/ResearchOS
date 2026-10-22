import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const CORPUS = path.resolve(__dirname, "../../eval/corpus/files");
const SHOTS = path.resolve(__dirname, "../../eval/results/screenshots");

test.describe.configure({ mode: "serial" });

test("full research workflow: project → upload → search → ask → cite → compare → report", async ({ page, request }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const name = `E2E 项目 ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByTestId("health")).toContainText(/未配置大模型|模型：/);

  // 1. create project
  await page.getByTestId("new-project-toggle").click();
  await page.getByLabel("项目名称").fill(name);
  await page.getByLabel("项目描述").fill("KX-200 轴承过热研究");
  await page.getByRole("button", { name: "创建项目" }).click();
  await expect(page.getByTestId("current-project")).toHaveText(name);

  // 2. upload the corpus (7 files incl. a scanned PDF)
  const files = fs.readdirSync(CORPUS).map((f) => path.join(CORPUS, f));
  await page.getByTestId("file-input").setInputFiles(files);
  const items = page.getByTestId("document-item");
  await expect(items).toHaveCount(files.length);
  await expect(page.locator('[data-testid="document-item"][data-status="pending"], [data-testid="document-item"][data-status="processing"]')).toHaveCount(0, { timeout: 60_000 });
  await expect(page.locator('[data-testid="document-item"][data-status="ready"]')).toHaveCount(files.length - 1);
  const ocr = page.locator('[data-testid="document-item"][data-status="needs_ocr"]');
  await expect(ocr).toHaveCount(1);
  await expect(ocr).toContainText("OCR");

  // duplicate upload is rejected with a visible error
  await page.getByTestId("file-input").setInputFiles(path.join(CORPUS, "maintenance_team_memo.md"));
  await expect(page.getByRole("alert").filter({ hasText: "重复" })).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "01-library.png") });

  // 3. evidence-grounded QA
  await page.getByLabel("研究问题").fill("激光对中检测显示的角向不对中是多少？");
  await page.getByTestId("ask-button").click();
  const answer = page.getByTestId("answer").last();
  await expect(answer).toBeVisible();
  await expect(answer).toHaveAttribute("data-status", /llm_unavailable|answered|partial/);
  await answer.getByTestId("evidence-item").first().click();
  const ev = page.getByTestId("evidence-panel");
  await expect(ev.getByTestId("evidence-doc-name")).toHaveText("kx200_revised_report_2024.pdf");
  await expect(ev.getByTestId("evidence-location")).toContainText("第 2 页");
  await expect(ev.getByTestId("highlight")).toContainText("0.35 mm/100 mm");
  await expect(ev.getByTestId("open-pdf-page")).toHaveAttribute("href", /#page=2$/);
  await page.screenshot({ path: path.join(SHOTS, "02-qa-citation.png") });

  // the cited original PDF is actually served
  const pdfHref = await ev.getByTestId("open-pdf-page").getAttribute("href");
  const pdf = await request.get(pdfHref!.split("#")[0]);
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  // 4. unanswerable question is refused
  await page.getByLabel("研究问题").fill("KX-200 泵的采购价格是多少？");
  await page.getByTestId("ask-button").click();
  const refused = page.getByTestId("answer").last();
  await expect(refused).toHaveAttribute("data-status", "insufficient_evidence");
  await expect(refused).toContainText("无法从当前资料中确认");

  // 5. hybrid search with document + page filters
  await page.getByRole("tab", { name: "检索" }).click();
  await page.getByLabel("检索查询").fill("补脂周期");
  await page.getByLabel("按文档过滤").selectOption({ label: "kx200_incident_report_2023.pdf" });
  await page.getByTestId("search-button").click();
  const results = page.getByTestId("search-result");
  await expect(results.first()).toContainText("kx200_incident_report_2023.pdf");
  for (const r of await results.all()) await expect(r).toContainText("kx200_incident_report_2023.pdf");
  await results.first().click();
  await expect(ev.getByTestId("highlight")).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "03-search.png") });

  // 6. cross-document comparison
  await page.getByRole("tab", { name: "跨文档比较" }).click();
  await page.getByLabel("比较问题").fill("比较这些文档对 KX-200 轴承过热根本原因的解释");
  await page.getByTestId("compare-button").click();
  const comp = page.getByTestId("comparison");
  await expect(comp).toBeVisible();
  await expect(comp.getByTestId("doc-evidence-card")).toHaveCount(files.length - 1);
  await expect(comp).toContainText("maintenance_team_memo.md");
  await page.screenshot({ path: path.join(SHOTS, "04-compare.png") });

  // 7. report: generate → preview → edit → save → download
  await page.getByRole("tab", { name: "研究报告" }).click();
  await page.getByLabel("报告研究问题").fill("KX-200 轴承过热的根本原因是什么？");
  await page.getByTestId("generate-report").click();
  const preview = page.getByTestId("report-preview");
  await expect(preview).toContainText("引用来源清单");
  await expect(preview).toContainText("执行摘要");
  await preview.getByTestId("citation-chip").first().click();
  await expect(ev.getByTestId("highlight")).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "05-report.png") });

  await page.getByRole("tab", { name: "编辑" }).click();
  const editor = page.getByTestId("report-editor");
  const original = await editor.inputValue();
  await editor.fill(original.replace("_（待撰写）_", "E2E 人工摘要：修订报告认定安装不对中为根本原因。"));
  await page.getByTestId("save-report").click();
  await expect(page.getByText("已保存")).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-report").click()]);
  const text = fs.readFileSync(await download.path(), "utf-8");
  expect(text).toContain("E2E 人工摘要");
  expect(text).toContain("## 引用来源清单");

  // 8. delete a document → it disappears and is no longer searchable
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("document-item").filter({ hasText: "kx200_field_notes_en.md" }).getByRole("button", { name: "删除" }).click();
  await expect(items).toHaveCount(files.length - 1);
  await page.getByRole("tab", { name: "检索" }).click();
  await page.getByLabel("按文档过滤").selectOption([]);
  await page.getByLabel("检索查询").fill("Site 7 misalignment");
  await page.getByTestId("search-button").click();
  await expect(page.getByTestId("search-results")).toBeVisible();
  await expect(page.getByTestId("search-results")).not.toContainText("kx200_field_notes_en.md");

  // cleanup
  const projects = await (await request.get("/api/projects")).json();
  const p = projects.find((x: { name: string }) => x.name === name);
  if (p) await request.delete(`/api/projects/${p.id}`);
});

test("mobile layout switches between library, workspace and evidence panes", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "面板切换" });
  await expect(nav).toBeVisible();
  await nav.getByRole("button", { name: "资料" }).click();
  await expect(page.getByRole("region", { name: "研究项目" })).toBeVisible();
  await nav.getByRole("button", { name: "证据" }).click();
  await expect(page.getByRole("region", { name: "研究项目" })).toBeHidden();
  await page.screenshot({ path: path.join(SHOTS, "06-mobile.png") });
  await ctx.close();
});
