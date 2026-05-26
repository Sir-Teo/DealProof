"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  Bot,
  CheckCircle2,
  CircleHelp,
  ExternalLink,
  FileText,
  Link,
  Loader2,
  NotebookPen,
  Paperclip,
  Plus,
  Quote,
  Send,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { API_BASE_URL, DEFAULT_DEAL, UI_COPY } from "@/lib/app-config";
import { effectiveDisposition, evidenceForClaim, scoreClaims } from "@/lib/scoring";
import type { ChatTurn, ClaimStatus, DealAnalysis, DealClaim, EvidenceItem, ReadinessStatus, ReviewerDisposition, ScoreSummary } from "@/lib/types";

const emptyCounts = { supported: 0, weak: 0, contradicted: 0, missing: 0 };
const DEAL_ID_KEY = "dealproofDealId";

type DealSummary = {
  id: string;
  company: string;
  stage: string;
  status: string;
  generatedAt: string | null;
  grade: "green" | "yellow" | "red" | null;
  materialCount: number;
};

type AgentEventStatus = "running" | "done" | "error";
type AgentEvent = {
  event: "run_start" | "step_start" | "tool_start" | "tool_delta" | "tool_complete" | "step_complete" | "run_complete" | "run_error";
  step: string;
  label: string;
  status: AgentEventStatus;
  toolName?: string;
  input?: string;
  output?: string;
  rawOutput?: string;
  webEvent?: string;
  query?: string;
  results?: number;
  claimId?: string;
  category?: string;
  importance?: string;
  sourceUrl?: string;
  sourceName?: string;
  stance?: string;
  relevanceScore?: string;
  webEvidence?: number;
  materials?: number;
  chunks?: number;
  claims?: number;
  evidence?: number;
};
type AgentToolRun = {
  step: string;
  label: string;
  status: AgentEventStatus;
  toolName?: string;
  input?: string;
  output?: string;
  rawOutput?: string;
  deltas: AgentEvent[];
  statsEvent: AgentEvent;
};
type FeedNote = { id: string; role: "user" | "agent"; title: string; body?: string };
type ClaimFilter = "needs_review" | "blockers" | "weak_missing" | "third_party_missing" | "verified" | "all";

const statusIcon: Record<ClaimStatus, typeof CheckCircle2> = {
  supported: CheckCircle2,
  weak: AlertTriangle,
  contradicted: XCircle,
  missing: CircleHelp
};

export default function Home() {
  const [deal, setDeal] = useState<DealAnalysis | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [urls, setUrls] = useState<string[]>([""]);
  const [question, setQuestion] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [attachOpen, setAttachOpen] = useState(false);
  const [feedNotes, setFeedNotes] = useState<FeedNote[]>([]);
  const [dealList, setDealList] = useState<DealSummary[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const feedWrapRef = useRef<HTMLElement>(null);
  const feedBottomRef = useRef<HTMLDivElement>(null);

  const claims = useMemo(() => deal?.claims ?? [], [deal?.claims]);
  const scoring = useMemo<ScoreSummary>(
    () => deal?.score ?? (claims.length ? scoreClaims(claims, deal?.evidence ?? [], deal?.qualityReview) : {
      overall: 0,
      grade: "red",
      counts: emptyCounts,
      drivers: ["No diligence claims were scored."]
    }),
    [claims, deal?.evidence, deal?.qualityReview, deal?.score]
  );
  const exportUrl = deal ? `${API_BASE_URL}/deals/${deal.id}/export-memo` : "#";
  const diligenceExportUrl = deal ? `${API_BASE_URL}/deals/${deal.id}/export-diligence-requests` : "#";
  const suggestedQuestions = useMemo(() => buildSuggestedQuestions(claims), [claims]);
  const isAnalyzing = busy === "analyze" || busy === "demo";
  const canRunAgent = Boolean(deal?.materials.length) && !isAnalyzing;

  useEffect(() => {
    feedBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [feedNotes.length, deal?.chatHistory?.length, isAnalyzing]);

  useEffect(() => {
    const savedId = localStorage.getItem(DEAL_ID_KEY);
    if (savedId) {
      api<DealAnalysis>(`/deals/${savedId}`)
        .then((d) => {
          setDeal(d);
          setAgentEvents([]);
          if (d.materials.length > 0 && !d.claims.length) {
            setQuestion(`Run full diligence analysis on ${d.company}`);
          }
        })
        .catch(() => localStorage.removeItem(DEAL_ID_KEY));
    }
    void loadDealList();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${path}`, init);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
    }
    return (await response.json()) as T;
  }

  async function readAgentStream(response: Response, onEvent: (event: AgentEvent) => void) {
    if (!response.body) throw new Error(UI_COPY.streamingUnavailable);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const parsed = JSON.parse(line.slice(6)) as Omit<AgentEvent, "status">;
        const status: AgentEventStatus = parsed.event === "run_error" ? "error" : parsed.event.endsWith("complete") ? "done" : "running";
        onEvent({ ...parsed, status });
      }
      if (done) break;
    }
  }

  async function loadDealList() {
    try {
      const list = await api<DealSummary[]>("/deals");
      setDealList(list);
    } catch { /* sidebar is non-critical */ }
  }

  function persistDeal(d: DealAnalysis) {
    localStorage.setItem(DEAL_ID_KEY, d.id);
    setDeal(d);
  }

  function newDeal() {
    localStorage.removeItem(DEAL_ID_KEY);
    setDeal(null);
    setAgentEvents([]);
    setFeedNotes([]);
    setPendingQuestion(null);
    setQuestion("");
    setFiles(null);
    setUrls([""]);
    setError(null);
    setSidebarOpen(false);
  }

  function resetComposerInputs() {
    setFiles(null);
    setUrls([""]);
    setAttachOpen(false);
  }

  async function switchDeal(id: string) {
    try {
      const d = await api<DealAnalysis>(`/deals/${id}`);
      localStorage.setItem(DEAL_ID_KEY, id);
      setDeal(d);
      setAgentEvents([]);
      setFeedNotes([]);
      setPendingQuestion(null);
      setQuestion("");
      resetComposerInputs();
      setError(null);
      setSidebarOpen(false);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    }
  }

  async function reviewClaim(
    claimId: string,
    reviewerDisposition: ReviewerDisposition,
    reviewerNotes?: string,
    resolutionRequest?: string
  ) {
    if (!deal) return;
    const reviewerStatus = reviewerDisposition === "verified" ? "verified" : reviewerDisposition === "needs_evidence" ? "needs_evidence" : "unreviewed";
    try {
      const updated = await api<DealAnalysis>(`/deals/${deal.id}/claims/${claimId}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewerStatus,
          reviewerDisposition,
          ...(reviewerNotes !== undefined && { reviewerNotes }),
          ...(resolutionRequest !== undefined && { resolutionRequest })
        }),
      });
      setDeal(updated);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    }
  }

  function addFeedNote(note: Omit<FeedNote, "id">) {
    setFeedNotes((notes) => [...notes.filter((item) => item.id !== "welcome"), { ...note, id: `${Date.now()}-${notes.length}` }]);
  }

  async function runAnalysisForDeal(targetDeal: DealAnalysis) {
    const response = await fetch(`${API_BASE_URL}/deals/${targetDeal.id}/analyze-stream`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
    }
    let streamError: string | null = null;
    await readAgentStream(response, (event) => {
      if (event.event === "run_error") streamError = event.label;
      setAgentEvents((events) => [...events, event]);
    });
    if (streamError) throw new Error(streamError);
    const analyzed = await api<DealAnalysis>(`/deals/${targetDeal.id}`);
    setDeal(analyzed);
    return analyzed;
  }

  async function ensureDeal() {
    if (deal) return deal;
    const created = await api<DealAnalysis>("/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: DEFAULT_DEAL.fallbackCompany, tagline: DEFAULT_DEAL.tagline, stage: DEFAULT_DEAL.stage })
    });
    persistDeal(created);
    setAgentEvents([]);
    setPendingQuestion(null);
    void loadDealList();
    return created;
  }

  async function loadDemoPacket(route: "/deals/demo" | "/deals/demo2" = "/deals/demo") {
    setBusy("demo");
    setError(null);
    try {
      const created = await api<DealAnalysis>(route, { method: "POST" });
      persistDeal(created);
      setAgentEvents([]);
      setFeedNotes([]);
      void loadDealList();
      setPendingQuestion(null);
      setQuestion("");
      resetComposerInputs();
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function runDemoEndToEnd() {
    setBusy("demo");
    setError(null);
    setAgentEvents([]);
    setFeedNotes([]);
    setPendingQuestion(null);
    setQuestion("");
    resetComposerInputs();
    try {
      const created = await api<DealAnalysis>("/deals/demo", { method: "POST" });
      persistDeal(created);
      void loadDealList();
      await runAnalysisForDeal(created);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  function updateUrl(index: number, value: string) {
    setUrls((prev) => prev.map((u, i) => (i === index ? value : u)));
  }

  function addUrl() {
    setUrls((prev) => [...prev, ""]);
  }

  function removeUrl(index: number) {
    setUrls((prev) => prev.length === 1 ? [""] : prev.filter((_, i) => i !== index));
  }

  async function uploadMaterials(event?: FormEvent) {
    event?.preventDefault();
    const nonEmptyUrls = urls.filter((u) => u.trim());
    if (!files?.length && !nonEmptyUrls.length) return;
    const invalidUrl = nonEmptyUrls.find((u) => !/^https?:\/\/.+/.test(u));
    if (invalidUrl) { setError(`Invalid URL — must start with http:// or https://`); return; }
    setBusy("upload");
    setError(null);
    try {
      const targetDeal = await ensureDeal();
      const form = new FormData();
      Array.from(files ?? []).forEach((file) => form.append("files", file));
      if (nonEmptyUrls[0]) form.append("url", nonEmptyUrls[0]);
      let updated = await api<DealAnalysis>(`/deals/${targetDeal.id}/materials`, { method: "POST", body: form });
      for (const urlItem of nonEmptyUrls.slice(1)) {
        const extra = new FormData();
        extra.append("url", urlItem);
        updated = await api<DealAnalysis>(`/deals/${targetDeal.id}/materials`, { method: "POST", body: extra });
      }
      setDeal(updated);
      setFiles(null);
      setUrls([""]);
      setAttachOpen(false);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function analyzeDeal() {
    if (!deal) return;
    setBusy("analyze");
    setError(null);
    setPendingQuestion(null);
    setAgentEvents([]);
    try {
      await runAnalysisForDeal(deal);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
      const refreshed = await api<DealAnalysis>(`/deals/${deal.id}`).catch(() => null);
      if (refreshed) setDeal(refreshed);
    } finally {
      setBusy(null);
    }
  }

  async function askQuestion(nextQuestion = question) {
    if (!deal) return;
    const trimmed = nextQuestion.trim();
    if (!trimmed) return;
    if (deal.materials.length > 0 && !deal.claims.length) {
      setQuestion("");
      await analyzeDeal();
      return;
    }
    setQuestion(trimmed);
    setBusy("chat");
    setPendingQuestion(trimmed);
    setError(null);
    try {
      const nextTurn = await api<ChatTurn>(`/deals/${deal.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed })
      });
      setDeal((current) => current ? { ...current, chatHistory: [...(current.chatHistory ?? []), nextTurn] } : current);
      setQuestion("");
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setPendingQuestion(null);
      setBusy(null);
    }
  }

  return (
    <div className="appWrap">
      {sidebarOpen && (
        <nav className="dealSidebar">
          <div className="sidebarHeader">
            <span className="sidebarTitle">Deals</span>
            <button className="iconButton" type="button" onClick={newDeal} title="New deal">
              <Plus size={15} />
            </button>
          </div>
          <ul className="dealList">
            {dealList.map((item) => (
              <li key={item.id}>
                <button
                  className={clsx("dealListItem", deal?.id === item.id && "dealListItem--active")}
                  type="button"
                  onClick={() => void switchDeal(item.id)}
                >
                  <span className="dealListCompany">{item.company}</span>
                  {item.grade && <span className={clsx("gradeChip gradeChip--sm", `card--${item.grade}`)}>{item.grade.toUpperCase()}</span>}
                </button>
              </li>
            ))}
            {dealList.length === 0 && <li className="dealListEmpty">No deals yet</li>}
          </ul>
        </nav>
      )}
      <main className="chatShell">
      <header className="appHeader">
        <div className="brandLine">
          <button className="iconButton sidebarToggle" type="button" onClick={() => setSidebarOpen((o) => !o)} title="Toggle deal list">
            <NotebookPen size={15} />
          </button>
          <span className="brandMark">
            <ShieldCheck size={16} />
          </span>
          <strong>{UI_COPY.appName}</strong>
        </div>
        <div className="headerActions">
          {deal && (
            <button className="iconButton" type="button" onClick={newDeal} title="New deal">
              <Plus size={15} />
            </button>
          )}
        </div>
      </header>

      <section className="feedWrap" ref={feedWrapRef}>
        <div className="messageFeed" aria-live="polite">
          {error && (
            <article className="systemBanner errorBanner">
              <XCircle size={15} />
              <span>{error}</span>
            </article>
          )}

          {!deal && !isAnalyzing && agentEvents.length === 0 && feedNotes.length === 0 && (
            <article className="message agentMessage">
              <div className={clsx("avatar", "done")}>
                <Bot size={14} />
              </div>
              <div className="messageBody welcomeState">
                <div className="messageMeta">
                  <strong>{UI_COPY.appName}</strong>
                </div>
                <p className="messageTitle">{UI_COPY.welcomeTitle}</p>
                <p className="messageCopy">{UI_COPY.welcomeBody}</p>
                <div className="welcomeActions">
                  <button className="primaryButton" type="button" onClick={() => void loadDemoPacket("/deals/demo")} disabled={Boolean(busy)}>
                    {busy === "demo" ? <Loader2 className="spin" size={13} /> : <ShieldCheck size={13} />}
                    {UI_COPY.seedDemoButton}
                  </button>
                  <button className="primaryButton" type="button" onClick={() => void loadDemoPacket("/deals/demo2")} disabled={Boolean(busy)}>
                    {busy === "demo" ? <Loader2 className="spin" size={13} /> : <ShieldCheck size={13} />}
                    {UI_COPY.seedDemo2Button}
                  </button>
                  <button className="secondaryButton" type="button" onClick={() => setAttachOpen(true)}>
                    <Upload size={13} />
                    {UI_COPY.uploadButton}
                  </button>
                </div>
              </div>
            </article>
          )}

          {feedNotes.map((note) => (
            <ChatBubble key={note.id} role={note.role} title={note.title} body={note.body} />
          ))}

          {(isAnalyzing || agentEvents.length > 0) && <AgentActivity events={agentEvents} running={isAnalyzing} />}

          {deal && deal.materials.length > 0 && !deal.claims.length && !isAnalyzing && (
            <MaterialsReady deal={deal} onRun={() => void analyzeDeal()} canRun={canRunAgent} />
          )}

          {deal && !isAnalyzing && (
            <AgentOutput
              deal={deal}
              scoring={scoring}
              exportUrl={exportUrl}
              diligenceExportUrl={diligenceExportUrl}
              onReviewClaim={reviewClaim}
            />
          )}

          {(deal?.chatHistory ?? []).map((turn) => (
            <ChatTurnMessage key={turn.id} turn={turn} />
          ))}

          {pendingQuestion && <ChatBubble role="user" title={pendingQuestion} />}

          {busy === "chat" && (
            <article className="message agentMessage">
              <Avatar status="running" />
              <div className="messageBody">
                <div className="messageMeta">
                  <strong>{UI_COPY.appName}</strong>
                </div>
                <p className="messageTitle">{UI_COPY.answeringTitle}</p>
              </div>
            </article>
          )}
          <div ref={feedBottomRef} />
        </div>
      </section>

      <form className="composer" onSubmit={(event) => { event.preventDefault(); void askQuestion(); }}>
        <div className="composerInner">
          {suggestedQuestions.length > 0 && (
            <div className="sampleQuestions">
              {suggestedQuestions.map((item) => (
                <button key={item} type="button" onClick={() => void askQuestion(item)} disabled={!deal?.claims.length || Boolean(busy)}>
                  {item}
                </button>
              ))}
            </div>
          )}
          <div className="composerCard">
            {deal && deal.materials.length > 0 && !deal.claims.length && !isAnalyzing && (
              <div className="attachedChips">
                {deal.materials.map((m) => (
                  <span key={m.id} className="attachedChip">
                    <FileText size={11} />
                    {m.name}
                  </span>
                ))}
              </div>
            )}
            {attachOpen && (
              <div className="attachDrawer">
                <div className="attachRow">
                  <label className="secondaryButton fileButton">
                    <Upload size={13} />
                    {files?.length ? `${files.length} file${files.length > 1 ? "s" : ""} selected` : UI_COPY.uploadButton}
                    <input
                      type="file"
                      multiple
                      accept=".pdf,.txt,.csv,.docx,.xlsx,.xls,.pptx,.ppt"
                      onChange={(event: ChangeEvent<HTMLInputElement>) => setFiles(event.target.files)}
                    />
                  </label>
                </div>
                <div className="urlList">
                  {urls.map((urlVal, idx) => (
                    <div key={idx} className="urlField">
                      <Link size={12} />
                      <input
                        value={urlVal}
                        onChange={(event) => updateUrl(idx, event.target.value)}
                        placeholder={UI_COPY.addUrlPlaceholder}
                      />
                      {urls.length > 1 && (
                        <button type="button" className="urlRemoveBtn" onClick={() => removeUrl(idx)} title="Remove">×</button>
                      )}
                    </div>
                  ))}
                  <button type="button" className="addUrlBtn" onClick={addUrl}><Plus size={11} />Add URL</button>
                </div>
                {error && busy !== "upload" && (
                  <p className="drawerError"><XCircle size={13} />{error}</p>
                )}
                <button className="secondaryButton" type="button" onClick={() => void uploadMaterials()} disabled={busy === "upload" || (!files?.length && !urls.some((u) => u.trim()))}>
                  {busy === "upload" ? <Loader2 className="spin" size={13} /> : <FileText size={13} />}
                  {UI_COPY.addMaterialButton}
                </button>
              </div>
            )}
            <div className="promptRow">
              <button
                className={clsx("iconButton", (files?.length || urls.some((u) => u.trim())) && "iconButton--active")}
                type="button"
                onClick={() => setAttachOpen((o) => !o)}
                title="Attach files or URL"
              >
                <Paperclip size={15} />
              </button>
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={deal?.claims.length ? "Ask a follow-up question..." : UI_COPY.questionPlaceholder}
                disabled={!deal || Boolean(busy)}
              />
              <button
                className={clsx("iconButton", "iconButton--send")}
                type="submit"
                disabled={!deal || Boolean(busy)}
                title="Send"
              >
                {busy === "chat" ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
              </button>
              <button
                className={clsx("iconButton", "iconButton--run", !canRunAgent && "iconButton--disabled")}
                type="button"
                onClick={() => void analyzeDeal()}
                disabled={!canRunAgent}
                title={UI_COPY.runAgentButton}
              >
                {isAnalyzing ? <Loader2 className="spin" size={15} /> : <Bot size={15} />}
              </button>
            </div>
            <div className="composerHint">
              <button className="hintLink" type="button" onClick={() => void runDemoEndToEnd()} disabled={Boolean(busy)}>
                {busy === "demo" ? <Loader2 className="spin" size={11} /> : null}
                Try demo
              </button>
            </div>
          </div>
        </div>
      </form>
      </main>
    </div>
  );
}

function ChatBubble({ role, title, body }: Omit<FeedNote, "id">) {
  return (
    <article className={clsx("message", role === "user" ? "userMessage" : "agentMessage")}>
      {role === "agent" && <Avatar status="done" />}
      <div className="messageBody">
        {role === "agent" && (
          <div className="messageMeta">
            <strong>{UI_COPY.appName}</strong>
          </div>
        )}
        <p className="messageTitle">{title}</p>
        {body && <p className="messageCopy">{body}</p>}
      </div>
    </article>
  );
}

function Avatar({ status }: { status: AgentEventStatus | "user" }) {
  return (
    <div className={clsx("avatar", status)}>
      {status === "running" ? <Loader2 className="spin" size={14} /> : status === "error" ? <XCircle size={14} /> : status === "user" ? null : <Bot size={14} />}
    </div>
  );
}

function AgentActivity({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const latest = events.at(-1);
  const latestProgress =
    [...events].reverse().find((event) => event.event === "step_start" || event.event === "run_start" || event.event === "run_complete" || event.event === "run_error") ?? latest;
  const tools = groupAgentTools(events);
  const visibleTools = tools.slice(running ? -4 : -7);
  const activityStatus = latest?.status ?? (running ? "running" : "done");
  const activityLabel = latestProgress?.label ?? UI_COPY.preparingAnalysis;

  return (
    <article className="message agentMessage">
      <Avatar status={activityStatus} />
      <div className="messageBody agentStream">
        <div className="messageMeta">
          <strong>{UI_COPY.appName}</strong>
        </div>
        <p className="messageTitle">{activityLabel}</p>
        <small>{latestProgress ? formatAgentStats(latestProgress) : UI_COPY.working}</small>
        {visibleTools.length > 0 && (
          <div className="toolStack">
            {visibleTools.map((tool) => (
              <ToolCallRow key={tool.step} tool={tool} />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

function groupAgentTools(events: AgentEvent[]) {
  const tools = new Map<string, AgentToolRun>();
  for (const event of events) {
    if (event.event !== "tool_start" && event.event !== "tool_delta" && event.event !== "tool_complete") continue;
    const existing = tools.get(event.step);
    const rawOutput = event.event === "tool_delta" ? `${existing?.rawOutput ?? ""}${event.rawOutput ?? ""}` : event.rawOutput ?? existing?.rawOutput;
    const deltas = event.event === "tool_delta" ? [...(existing?.deltas ?? []), event] : existing?.deltas ?? [];
    tools.set(event.step, {
      step: event.step,
      label: event.label,
      status: event.status,
      toolName: event.toolName ?? existing?.toolName,
      input: event.input ?? existing?.input,
      output: event.output ?? existing?.output,
      rawOutput,
      deltas,
      statsEvent: event
    });
  }
  return Array.from(tools.values());
}

function ToolCallRow({ tool }: { tool: AgentToolRun }) {
  const toolName = tool.toolName ?? tool.step;
  return (
    <details className={clsx("toolCall", tool.status)}>
      <summary>
        {tool.status === "running" ? <Loader2 className="spin" size={13} /> : tool.status === "error" ? <XCircle size={13} /> : <CheckCircle2 size={13} />}
        <strong>{formatToolName(toolName)}</strong>
        <span>{formatAgentStats(tool.statsEvent)}</span>
      </summary>
      <dl>
        <div>
          <dt>{UI_COPY.inputLabel}</dt>
          <dd>{tool.input ?? UI_COPY.defaultToolInput}</dd>
        </div>
        <div>
          <dt>{UI_COPY.outputLabel}</dt>
          <dd>{tool.output ?? UI_COPY.waitingForResult}</dd>
        </div>
        {tool.deltas.some((event) => event.webEvent) && (
          <div>
            <dt>Research</dt>
            <dd>
              <WebResearchLog events={tool.deltas} />
            </dd>
          </div>
        )}
        {tool.rawOutput && !tool.deltas.some((event) => event.webEvent) && (
          <div>
            <dt>DeepSeek</dt>
            <dd className="rawModelOutput">{tool.rawOutput}</dd>
          </div>
        )}
      </dl>
    </details>
  );
}

function WebResearchLog({ events }: { events: AgentEvent[] }) {
  const visible = events.filter((event) => event.webEvent).slice(-12);
  return (
    <ol className="webResearchLog">
      {visible.map((event, index) => (
        <li key={`${event.webEvent}-${index}-${event.label}`}>
          <span className={clsx("webEventBadge", event.webEvent)}>{formatWebEvent(event)}</span>
          <div>
            <strong>{event.label}</strong>
            <small>{formatWebEventMeta(event)}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}

function formatWebEvent(event: AgentEvent) {
  const labels: Record<string, string> = {
    web_start: "Start",
    web_claim: "Claim",
    web_query: "Search",
    web_results: "Results",
    web_fetch: "Fetch",
    web_evidence: "Evidence",
    web_complete: "Done",
    web_disabled: "Off",
    web_error: "Error"
  };
  return labels[event.webEvent ?? ""] ?? "Web";
}

function formatWebEventMeta(event: AgentEvent) {
  if (event.webEvent === "web_query") return event.query ?? "";
  if (event.webEvent === "web_results") return `${event.results ?? 0} results`;
  if (event.webEvent === "web_fetch") return event.sourceUrl ?? "";
  if (event.webEvent === "web_evidence") {
    const stance = event.stance?.replaceAll("_", " ") ?? "evidence";
    const score = event.relevanceScore ? ` · relevance ${event.relevanceScore}` : "";
    return `${stance}${score}`;
  }
  if (event.webEvent === "web_claim") return [event.claimId, event.category, event.importance].filter(Boolean).join(" · ");
  if (event.webEvidence !== undefined) return `${event.webEvidence} public evidence`;
  return "";
}

function MaterialsReady({ deal, onRun, canRun }: { deal: DealAnalysis; onRun: () => void; canRun: boolean }) {
  return (
    <article className="message agentMessage">
      <Avatar status="done" />
      <div className="messageBody materialsReady">
        <div className="messageMeta">
          <strong>{UI_COPY.appName}</strong>
        </div>
        <div className="materialsReadyHeader">
          <div>
            <p className="messageTitle">{UI_COPY.demoReadyTitle}</p>
            <p className="messageCopy">{deal.materials.length} source materials are staged for {deal.company}.</p>
          </div>
          <button className="primaryButton" type="button" onClick={onRun} disabled={!canRun}>
            <Bot size={13} />
            {UI_COPY.runAgentButton}
          </button>
        </div>
        <div className="materialsTable">
          {deal.materials.map((material) => (
            <div key={material.id} className="materialRow">
              <FileText size={13} />
              <div>
                <strong>{material.name}</strong>
                <span>{material.kind} · {material.summary || material.excerpt || "Ready for parsing."}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function AgentOutput({ deal, scoring, exportUrl, diligenceExportUrl, onReviewClaim }: {
  deal: DealAnalysis;
  scoring: ReturnType<typeof scoreClaims>;
  exportUrl: string;
  diligenceExportUrl: string;
  onReviewClaim: (claimId: string, disposition: ReviewerDisposition, notes?: string, resolutionRequest?: string) => void;
}) {
  const [claimFilter, setClaimFilter] = useState<ClaimFilter>("all");
  if (!deal.materials.length) return null;
  const memo = deal.memo;
  const claims = deal.claims;
  const risks = memo?.keyRisks?.length ? memo.keyRisks : (memo?.materialRisks ?? []);
  const diligenceRequests = deal.qualityReview?.approvedDiligenceRequests?.length
    ? deal.qualityReview.approvedDiligenceRequests
    : memo?.nextDiligenceRequests?.length ? memo.nextDiligenceRequests : (memo?.followUpQuestions ?? []);
  const filterCounts = buildClaimFilterCounts(claims, deal.evidence);
  const filteredClaims = claims.filter((claim) => claimMatchesFilter(claim, claimFilter, deal.evidence));
  const workspaceGroups = buildWorkspaceGroups(filteredClaims, deal.evidence);
  const readinessLabel = formatReadiness(deal.qualityReview?.readinessStatus);

  return (
    <div className="agentOutput">
      {memo && (
        <div className={clsx("gradeBar", `card--${scoring.grade}`)}>
          <strong>{readinessLabel} · {scoring.grade} · {scoring.overall}/100</strong>
          <span>{deal.qualityReview?.topGatingIssue || memo.icRecommendation}</span>
        </div>
      )}

      {memo && (
        <section className="artifactPanel memoArtifact">
          <div className="artifactPanelHeader">
            <div>
              <p className="eyebrow">{UI_COPY.memoEyebrow}</p>
              <h2>{UI_COPY.memoTitle}</h2>
            </div>
            <a className="primaryButton" href={exportUrl}>
              <ArrowDownToLine size={14} />
              {UI_COPY.exportMarkdownButton}
            </a>
          </div>
          {deal.profile && (
            <div className="profileGrid">
              <Metric label="Sector" value={deal.profile.sector} />
              <Metric label="Model" value={deal.profile.businessModel} />
              <Metric label="Customer" value={deal.profile.customer} />
              <Metric label="Stage" value={deal.profile.stage} />
            </div>
          )}
          {memo.executiveSummary && (
            <section className="memoNarrative">
              <h3>{UI_COPY.executiveSummaryTitle}</h3>
              <p>{memo.executiveSummary}</p>
            </section>
          )}
          {memo.thesisAssessment && (
            <section className="memoNarrative">
              <h3>{UI_COPY.thesisAssessmentTitle}</h3>
              <p>{memo.thesisAssessment}</p>
            </section>
          )}
          {memo.investmentQuestion && <p className="memoQuestion">{memo.investmentQuestion}</p>}
          {scoring.drivers.length > 0 && (
            <div className="scoreDrivers">
              <strong>IC readiness drivers</strong>
              <ul>
                {scoring.drivers.map((driver) => (
                  <li key={driver}>{driver}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="memoColumns">
            <MemoSection title={UI_COPY.keyStrengthsTitle} items={memo.keyStrengths} />
            <MemoSection title={UI_COPY.materialRisksTitle} items={risks} danger />
            <MemoSection title={UI_COPY.followUpQuestionsTitle} items={diligenceRequests} />
          </div>
          <div className="recommendation">{memo.icRecommendation}</div>
        </section>
      )}

      {claims.length > 0 && (
        <section className="artifactPanel">
          <div className="artifactPanelHeader">
            <div>
              <p className="eyebrow">Claim review workspace</p>
              <h2>{claims.length} auditable work items</h2>
            </div>
            <a className="secondaryButton" href={diligenceExportUrl}>
              <ArrowDownToLine size={14} />
              Export requests
            </a>
          </div>
          {deal.qualityReview && (
            <div className="readinessStrip">
              <Metric label="Readiness" value={readinessLabel} />
              <Metric label="Top issue" value={deal.qualityReview.topGatingIssue || "No unresolved IC blockers."} />
              <Metric label="Open requests" value={String(diligenceRequests.length)} />
            </div>
          )}
          <ClaimFilterBar active={claimFilter} counts={filterCounts} onChange={setClaimFilter} />
          <div className="claimGroups">
            {workspaceGroups.map(({ key, title, items }) => {
              if (!items.length) return null;
              return (
                <section key={key} className="claimGroup">
                  <h3>{title}</h3>
                  {items.map((claim) => {
                    const claimEvidence = evidenceForClaim(claim.id, deal.evidence);
                    const disposition = effectiveDisposition(claim);
                    return (
                      <div key={claim.id} className="claimRow">
                        <div className="claimRowMain">
                          <StatusPill status={claim.status} />
                          <span className="claimText" title={claim.text}>{claim.text}</span>
                          <small>{claimEvidence.length} {UI_COPY.evidenceLabel} · {claim.confidence} confidence · {claim.decisionImpact} impact</small>
                        </div>
                        <div className="reviewButtons">
                          <button
                            type="button"
                            className={clsx("reviewBtn", disposition === "verified" && "reviewBtn--active reviewBtn--verified")}
                            onClick={() => onReviewClaim(claim.id, disposition === "verified" ? "unreviewed" : "verified")}
                            title="Mark verified"
                          >✓ Verified</button>
                          <button
                            type="button"
                            className={clsx("reviewBtn", disposition === "needs_evidence" && "reviewBtn--active reviewBtn--needs")}
                            onClick={() => onReviewClaim(claim.id, disposition === "needs_evidence" ? "unreviewed" : "needs_evidence")}
                            title="Needs more evidence"
                          >? Needs evidence</button>
                          <button
                            type="button"
                            className={clsx("reviewBtn", disposition === "ic_blocker" && "reviewBtn--active reviewBtn--blocker")}
                            onClick={() => onReviewClaim(claim.id, disposition === "ic_blocker" ? "unreviewed" : "ic_blocker")}
                            title="Mark IC blocker"
                          >! IC blocker</button>
                          <button
                            type="button"
                            className={clsx("reviewBtn", disposition === "ignored" && "reviewBtn--active")}
                            onClick={() => onReviewClaim(claim.id, disposition === "ignored" ? "unreviewed" : "ignored")}
                            title="Ignore claim"
                          >Ignore</button>
                        </div>
                        <div className="claimReason">
                          <strong>Why:</strong> {claim.statusReason || claim.riskRationale}
                        </div>
                        {claim.resolutionRequest && (
                          <div className="resolutionRequest">
                            <strong>Request:</strong>
                            <input
                              defaultValue={claim.resolutionRequest}
                              onBlur={(event) => {
                                if (event.currentTarget.value !== claim.resolutionRequest) {
                                  onReviewClaim(claim.id, disposition, claim.reviewerNotes, event.currentTarget.value);
                                }
                              }}
                              aria-label={`Diligence request for ${claim.id}`}
                            />
                          </div>
                        )}
                        {claimEvidence.length > 0 && (
                          <details className="claimEvidence">
                            <summary>View</summary>
                            <div className="claimEvidencePanel">
                              {claimEvidence.map((item) => (
                                <article key={item.id} className={clsx("evidenceItem", `evidenceItem--${item.stance}`, `source--${item.sourceIndependence}`)}>
                                  <header className="citationHeader">
                                    <div className="citationTitle">
                                      <span>{item.stance.replaceAll("_", " ")} · {item.sourceIndependence.replaceAll("_", " ")}</span>
                                      <strong>{sourceLabel(item)}</strong>
                                    </div>
                                    {item.sourceUrl && (
                                      <a className="sourceLink" href={item.sourceUrl} target="_blank" rel="noreferrer">
                                        <ExternalLink size={13} />
                                        Open source
                                      </a>
                                    )}
                                  </header>
                                  <blockquote className="quoteBlock">
                                    <Quote size={14} />
                                    <p>{item.quoteSpan || item.snippet}</p>
                                  </blockquote>
                                </article>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    );
                  })}
                </section>
              );
            })}
            {filteredClaims.length === 0 && (
              <p className="emptyFilteredClaims">No claims match this view.</p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChatTurnMessage({ turn }: { turn: ChatTurn }) {
  return (
    <>
      <ChatBubble role="user" title={turn.question} />
      <AnswerMessage answer={turn} />
    </>
  );
}

function AnswerMessage({ answer }: { answer: Pick<ChatTurn, "answer" | "citations"> }) {
  return (
    <article className="message agentMessage">
      <Avatar status="done" />
      <div className="messageBody answerBox">
        <div className="messageMeta">
          <strong>{UI_COPY.appName}</strong>
        </div>
        <p className="messageCopy">{answer.answer}</p>
        <footer>
          {answer.citations.map((citation, index) => (
            <span key={citation} className="chatCitationChip">
              <small>{index + 1}</small>
              {shortCitation(citation)}
            </span>
          ))}
        </footer>
      </div>
    </article>
  );
}

function StatusPill({ status }: { status: ClaimStatus }) {
  const Icon = statusIcon[status];
  return (
    <span className={clsx("statusPill", status)}>
      <Icon size={12} />
      {status}
    </span>
  );
}

function ClaimFilterBar({ active, counts, onChange }: {
  active: ClaimFilter;
  counts: Record<ClaimFilter, number>;
  onChange: (filter: ClaimFilter) => void;
}) {
  const filters: Array<{ key: ClaimFilter; label: string }> = [
    { key: "needs_review", label: "Needs review" },
    { key: "blockers", label: "Blockers" },
    { key: "weak_missing", label: "Weak/missing" },
    { key: "third_party_missing", label: "No third-party" },
    { key: "verified", label: "Verified" },
    { key: "all", label: "All" },
  ];
  return (
    <div className="claimFilters" role="group" aria-label="Claim review filters">
      {filters.map((filter) => (
        <button
          key={filter.key}
          type="button"
          className={clsx(active === filter.key && "claimFilter--active")}
          onClick={() => onChange(filter.key)}
        >
          {filter.label}
          <span>{counts[filter.key]}</span>
        </button>
      ))}
    </div>
  );
}

function MemoSection({ title, items, danger = false }: { title: string; items: string[]; danger?: boolean }) {
  return (
    <section className={clsx("memoSection", danger && "danger")}>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function formatToolName(toolName: string) {
  return toolName.replaceAll("_", " ");
}

function formatAgentStats(event: AgentEvent) {
  const stats = [
    event.materials !== undefined && `${event.materials} materials`,
    event.chunks !== undefined && `${event.chunks} chunks`,
    event.claims !== undefined && `${event.claims} claims`,
    event.evidence !== undefined && `${event.evidence} evidence`
  ].filter(Boolean);
  if (event.status === "error") return UI_COPY.needsAttention;
  return stats.join(" / ") || (event.status === "done" ? UI_COPY.complete : UI_COPY.working);
}

function buildSuggestedQuestions(claims: DealClaim[]) {
  const riskyClaims = claims.filter((claim) => claim.status !== "supported");
  const candidates = riskyClaims.length ? riskyClaims : claims;
  return Array.from(new Set(candidates.map((claim) => `What evidence supports the ${formatClaimCategory(claim.category)} claim?`))).slice(0, 3);
}

function formatClaimCategory(category: DealClaim["category"]) {
  return category.replaceAll("_", " ");
}

function claimMatchesFilter(claim: DealClaim, filter: ClaimFilter, evidence: EvidenceItem[]) {
  const disposition = effectiveDisposition(claim);
  const hasThirdParty = evidenceForClaim(claim.id, evidence).some((item) => item.sourceIndependence === "third_party");
  if (filter === "all") return true;
  if (filter === "verified") return disposition === "verified";
  if (filter === "blockers") return disposition === "ic_blocker" || (claim.status === "contradicted" && claim.decisionImpact === "high");
  if (filter === "weak_missing") return claim.status === "weak" || claim.status === "missing";
  if (filter === "third_party_missing") return claim.status === "supported" && !hasThirdParty;
  return disposition !== "verified" && disposition !== "ignored" && (
    claim.status !== "supported" ||
    !hasThirdParty ||
    disposition === "needs_evidence" ||
    disposition === "ic_blocker"
  );
}

function buildClaimFilterCounts(claims: DealClaim[], evidence: EvidenceItem[]) {
  const counts = {
    needs_review: 0,
    blockers: 0,
    weak_missing: 0,
    third_party_missing: 0,
    verified: 0,
    all: claims.length,
  } satisfies Record<ClaimFilter, number>;
  for (const claim of claims) {
    (Object.keys(counts) as ClaimFilter[]).forEach((filter) => {
      if (filter !== "all" && claimMatchesFilter(claim, filter, evidence)) counts[filter] += 1;
    });
  }
  return counts;
}

function buildWorkspaceGroups(claims: DealClaim[], evidence: EvidenceItem[]) {
  const evidenceByClaim = new Map<string, EvidenceItem[]>();
  for (const item of evidence) {
    evidenceByClaim.set(item.claimId, [...(evidenceByClaim.get(item.claimId) ?? []), item]);
  }
  const blockers: DealClaim[] = [];
  const needsEvidence: DealClaim[] = [];
  const monitor: DealClaim[] = [];
  const verified: DealClaim[] = [];
  for (const claim of claims) {
    const disposition = effectiveDisposition(claim);
    const hasThirdParty = (evidenceByClaim.get(claim.id) ?? []).some((item) => item.sourceIndependence === "third_party");
    if (disposition === "verified") verified.push(claim);
    else if (disposition === "ic_blocker" || (claim.status === "contradicted" && claim.decisionImpact === "high")) blockers.push(claim);
    else if (disposition === "needs_evidence" || claim.status === "missing" || claim.status === "weak" || (claim.status === "supported" && !hasThirdParty)) needsEvidence.push(claim);
    else monitor.push(claim);
  }
  return [
    { key: "blockers", title: "Blockers", items: blockers },
    { key: "needs-evidence", title: "Needs evidence", items: needsEvidence },
    { key: "monitor", title: "Monitor", items: monitor },
    { key: "verified", title: "Verified", items: verified },
  ];
}

function formatReadiness(status?: ReadinessStatus) {
  if (status === "ic_ready") return "IC-ready";
  if (status === "blocked") return "Blocked";
  if (status === "screen_out") return "Screen out";
  return "Needs diligence";
}

function sourceLabel(item: EvidenceItem) {
  return item.sourceName || item.citation.split(", chunk")[0] || "Source";
}

function shortCitation(citation: string) {
  return citation.replace(/,\s*chunk\s*/i, " #");
}
