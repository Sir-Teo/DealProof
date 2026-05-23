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
  Paperclip,
  Quote,
  Send,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { API_BASE_URL, DEFAULT_DEAL, UI_COPY } from "@/lib/app-config";
import { evidenceForClaim, scoreClaims } from "@/lib/scoring";
import type { ChatTurn, ClaimStatus, DealAnalysis, DealClaim, EvidenceItem } from "@/lib/types";

const emptyCounts = { supported: 0, weak: 0, contradicted: 0, missing: 0 };

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
  const feedWrapRef = useRef<HTMLElement>(null);
  const feedBottomRef = useRef<HTMLDivElement>(null);

  const claims = useMemo(() => deal?.claims ?? [], [deal?.claims]);
  const scoring = useMemo(() => (claims.length ? scoreClaims(claims) : { overall: 0, grade: "red" as const, counts: emptyCounts }), [claims]);
  const exportUrl = deal ? `${API_BASE_URL}/deals/${deal.id}/export-memo` : "#";
  const suggestedQuestions = useMemo(() => buildSuggestedQuestions(claims), [claims]);
  const isAnalyzing = busy === "analyze" || busy === "demo";
  const canRunAgent = Boolean(deal?.materials.length) && !isAnalyzing;

  useEffect(() => {
    feedBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [feedNotes.length, deal?.chatHistory?.length, isAnalyzing]);

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
    addFeedNote({
      role: "agent",
      title: UI_COPY.analysisCompleteTitle,
      body: `${analyzed.claims.length} claims, ${analyzed.evidence.length} evidence items, ${scoreClaims(analyzed.claims).grade.toUpperCase()} risk.`
    });
    return analyzed;
  }

  async function ensureDeal() {
    if (deal) return deal;
    const created = await api<DealAnalysis>("/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: DEFAULT_DEAL.fallbackCompany, tagline: DEFAULT_DEAL.tagline, stage: DEFAULT_DEAL.stage })
    });
    setDeal(created);
    setAgentEvents([]);
    setPendingQuestion(null);
    return created;
  }

  async function loadDemoPacket() {
    setBusy("demo");
    setError(null);
    try {
      const created = await api<DealAnalysis>("/deals/demo", { method: "POST" });
      setDeal(created);
      setPendingQuestion(null);
      setQuestion("");
      setAgentEvents([]);
      setFeedNotes([]);
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
    <main className="chatShell">
      <header className="appHeader">
        <div className="brandLine">
          <span className="brandMark">
            <ShieldCheck size={16} />
          </span>
          <strong>{UI_COPY.appName}</strong>
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

          {feedNotes.map((note) => (
            <ChatBubble key={note.id} role={note.role} title={note.title} body={note.body} />
          ))}

          {(isAnalyzing || agentEvents.length > 0) && <AgentActivity events={agentEvents} running={isAnalyzing} />}

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

          {deal && !isAnalyzing && (
            <AgentOutput
              deal={deal}
              scoring={scoring}
              exportUrl={exportUrl}
            />
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
            {attachOpen && (
              <div className="attachDrawer">
                <div className="attachRow">
                  <label className="secondaryButton fileButton">
                    <Upload size={13} />
                    {files?.length ? `${files.length} file${files.length > 1 ? "s" : ""} selected` : UI_COPY.uploadButton}
                    <input
                      type="file"
                      multiple
                      accept=".pdf,.txt,.csv,.docx"
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
                  <button type="button" className="addUrlBtn" onClick={addUrl}>+ URL</button>
                </div>
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
                placeholder={UI_COPY.questionPlaceholder}
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
              <button className="hintLink" type="button" onClick={() => void loadDemoPacket()} disabled={Boolean(busy)}>
                {busy === "demo" ? <Loader2 className="spin" size={11} /> : null}
                Try demo
              </button>
            </div>
          </div>
        </div>
      </form>
    </main>
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

function AgentOutput({ deal, scoring, exportUrl }: {
  deal: DealAnalysis;
  scoring: ReturnType<typeof scoreClaims>;
  exportUrl: string;
}) {
  if (!deal.materials.length) return null;
  const memo = deal.memo;
  const claims = deal.claims;
  const risks = memo?.keyRisks?.length ? memo.keyRisks : (memo?.materialRisks ?? []);
  const diligenceRequests = memo?.nextDiligenceRequests?.length ? memo.nextDiligenceRequests : (memo?.followUpQuestions ?? []);

  return (
    <div className="agentOutput">
      {memo && (
        <div className={clsx("gradeBar", `card--${memo.overallGrade?.toLowerCase()}`)}>
          <strong>{memo.overallGrade}</strong>
          <span>{memo.icRecommendation}</span>
        </div>
      )}

      {memo && (
        <section className="artifactPanel memoArtifact">
          <div className="artifactPanelHeader">
            <h2>{UI_COPY.memoTitle}</h2>
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
            <h2>{claims.length} diligence claims</h2>
            <span className={clsx("gradeChip", `card--${scoring.grade}`)}>
              {scoring.counts.weak + scoring.counts.contradicted + scoring.counts.missing} {UI_COPY.exceptionsNeedReview}
            </span>
          </div>
          <div className="claimGroups">
            {(["contradicted", "weak", "missing", "supported"] as ClaimStatus[]).map((status) => {
              const items = claims.filter((claim) => claim.status === status);
              if (!items.length) return null;
              return (
                <section key={status} className="claimGroup">
                  <h3>{status}</h3>
                  {items.map((claim) => {
                    const claimEvidence = evidenceForClaim(claim.id, deal.evidence);
                    return (
                      <div key={claim.id} className="claimRow">
                        <StatusPill status={claim.status} />
                        <span className="claimText" title={claim.text}>{claim.text}</span>
                        <small>{claimEvidence.length} {UI_COPY.evidenceLabel}</small>
                        {claimEvidence.length > 0 && (
                          <details className="claimEvidence">
                            <summary>View</summary>
                            <div className="claimEvidencePanel">
                              {claimEvidence.map((item) => (
                                <article key={item.id} className={clsx("evidenceItem", `evidenceItem--${item.stance}`)}>
                                  <header className="citationHeader">
                                    <div className="citationTitle">
                                      <span>{item.stance.replaceAll("_", " ")}</span>
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

function sourceLabel(item: EvidenceItem) {
  return item.sourceName || item.citation.split(", chunk")[0] || "Source";
}

function shortCitation(citation: string) {
  return citation.replace(/,\s*chunk\s*/i, " #");
}
