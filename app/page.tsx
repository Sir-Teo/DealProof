"use client";

import { useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  Bot,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Gauge,
  Link,
  Loader2,
  MessageSquarePlus,
  PanelRightOpen,
  Paperclip,
  Quote,
  Send,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { API_BASE_URL, DEFAULT_DEAL, UI_COPY } from "@/lib/app-config";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";
import type { ChatAnswer, ClaimStatus, DealAnalysis, DealClaim, EvidenceItem } from "@/lib/types";

const emptyCounts = { supported: 0, weak: 0, contradicted: 0, missing: 0 };

type AgentEventStatus = "running" | "done" | "error";
type AgentEvent = {
  event: "run_start" | "step_start" | "tool_start" | "tool_complete" | "step_complete" | "run_complete" | "run_error";
  step: string;
  label: string;
  status: AgentEventStatus;
  toolName?: string;
  input?: string;
  output?: string;
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
  statsEvent: AgentEvent;
};
type ActiveArtifact = { type: "claims" } | { type: "memo" } | { type: "claim"; claimId: string } | null;
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
  const [url, setUrl] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<ActiveArtifact>(null);
  const [attachOpen, setAttachOpen] = useState(false);
  const [feedNotes, setFeedNotes] = useState<FeedNote[]>([
    {
      id: "welcome",
      role: "agent",
      title: UI_COPY.welcomeTitle,
      body: UI_COPY.welcomeBody
    }
  ]);

  const claims = useMemo(() => deal?.claims ?? [], [deal?.claims]);
  const scoring = useMemo(() => (claims.length ? scoreClaims(claims) : { overall: 0, grade: "red" as const, counts: emptyCounts }), [claims]);
  const selectedClaim =
    activeArtifact?.type === "claim" ? claims.find((claim) => claim.id === activeArtifact.claimId) ?? claims[0] ?? null : claims[0] ?? null;
  const selectedEvidence = selectedClaim && deal ? evidenceForClaim(selectedClaim.id, deal.evidence) : [];
  const memoMarkdown = deal?.memo ? generateMemoMarkdown(deal.memo) : "";
  const exportUrl = deal ? `${API_BASE_URL}/deals/${deal.id}/export-memo` : "#";
  const suggestedQuestions = useMemo(() => buildSuggestedQuestions(claims), [claims]);
  const isAnalyzing = busy === "analyze";
  const canRunAgent = Boolean(deal?.materials.length) && !isAnalyzing;

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

  async function ensureDeal() {
    if (deal) return deal;
    const created = await api<DealAnalysis>("/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: DEFAULT_DEAL.fallbackCompany, tagline: DEFAULT_DEAL.tagline, stage: DEFAULT_DEAL.stage })
    });
    setDeal(created);
    setAgentEvents([]);
    setAnswer(null);
    addFeedNote({ role: "user", title: `${UI_COPY.createdDealPrefix} ${created.company}`, body: created.tagline });
    return created;
  }

  async function loadDemoPacket() {
    setBusy("demo");
    setError(null);
    try {
      const created = await api<DealAnalysis>("/deals/demo", { method: "POST" });
      setDeal(created);
      setAnswer(null);
      setAgentEvents([]);
      setActiveArtifact(null);
      addFeedNote({ role: "user", title: `${UI_COPY.seededDealPrefix} ${created.company}`, body: `${created.materials.length} ${UI_COPY.sourceMaterialsLoaded}` });
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function uploadMaterials(event?: FormEvent) {
    event?.preventDefault();
    if (!files?.length && !url.trim()) return;
    setBusy("upload");
    setError(null);
    try {
      const targetDeal = await ensureDeal();
      const form = new FormData();
      Array.from(files ?? []).forEach((file) => form.append("files", file));
      if (url.trim()) form.append("url", url.trim());
      const updated = await api<DealAnalysis>(`/deals/${targetDeal.id}/materials`, { method: "POST", body: form });
      setDeal(updated);
      addFeedNote({
        role: "user",
        title: UI_COPY.addedMaterialTitle,
        body: `${Array.from(files ?? []).map((file) => file.name).join(", ") || url.trim()}`
      });
      setFiles(null);
      setUrl("");
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
    setAnswer(null);
    setAgentEvents([]);
    setActiveArtifact(null);
    addFeedNote({ role: "user", title: UI_COPY.runAgentTitle, body: `${deal.materials.length} ${UI_COPY.materialsQueued}` });
    try {
      const response = await fetch(`${API_BASE_URL}/deals/${deal.id}/analyze-stream`, { method: "POST" });
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
      const analyzed = await api<DealAnalysis>(`/deals/${deal.id}`);
      setDeal(analyzed);
      setActiveArtifact({ type: "claims" });
      addFeedNote({
        role: "agent",
        title: UI_COPY.analysisCompleteTitle,
        body: `${analyzed.claims.length} claims, ${analyzed.evidence.length} evidence items, ${scoreClaims(analyzed.claims).grade.toUpperCase()} risk.`
      });
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
    setAnswer(null);
    setError(null);
    addFeedNote({ role: "user", title: trimmed });
    try {
      const nextAnswer = await api<ChatAnswer>(`/deals/${deal.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed })
      });
      setAnswer(nextAnswer);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function updateClaimReview(claimId: string, payload: { status?: ClaimStatus; reviewerStatus?: DealClaim["reviewerStatus"]; reviewerNotes?: string }) {
    if (!deal) return;
    setError(null);
    try {
      const updated = await api<DealAnalysis>(`/deals/${deal.id}/claims/${claimId}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      setDeal(updated);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
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

      <section className="feedWrap">
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

          {answer && <AnswerMessage answer={answer} />}

          {deal && (
            <ResultArtifacts
              deal={deal}
              scoring={scoring}
              activeArtifact={activeArtifact}
              selectedClaim={selectedClaim}
              selectedEvidence={selectedEvidence}
              memoMarkdown={memoMarkdown}
              exportUrl={exportUrl}
              onOpenClaims={() => setActiveArtifact({ type: "claims" })}
              onOpenMemo={() => setActiveArtifact({ type: "memo" })}
              onSelectClaim={(claim) => setActiveArtifact({ type: "claim", claimId: claim.id })}
              onUpdateClaimReview={updateClaimReview}
            />
          )}
        </div>
      </section>

      <form className="composer" onSubmit={(event) => { event.preventDefault(); void askQuestion(); }}>
        <div className="composerInner">
          {suggestedQuestions.length > 0 && (
            <div className="sampleQuestions">
              {suggestedQuestions.map((item) => (
                <button key={item} type="button" onClick={() => void askQuestion(item)} disabled={!deal?.claims.length}>
                  {item}
                </button>
              ))}
            </div>
          )}
          <div className="composerCard">
            <div className="promptArea">
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={UI_COPY.questionPlaceholder}
                disabled={!deal}
              />
              <button className="sendButton" type="submit" disabled={!deal || busy === "chat"}>
                {busy === "chat" ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
              </button>
            </div>
            <div className="composerDivider" />
            {attachOpen && (
              <div className="attachDrawer">
                <label className="secondaryButton fileButton">
                  <Upload size={13} />
                  {UI_COPY.uploadButton}
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.txt,.csv,.docx"
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setFiles(event.target.files)}
                  />
                </label>
                <div className="urlField">
                  <Link size={12} />
                  <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder={UI_COPY.addUrlPlaceholder} />
                </div>
                <button className="secondaryButton" type="button" onClick={() => void uploadMaterials()} disabled={busy === "upload" || (!files?.length && !url.trim())}>
                  {busy === "upload" ? <Loader2 className="spin" size={13} /> : <FileText size={13} />}
                  {UI_COPY.addMaterialButton}
                </button>
              </div>
            )}
            <div className="composerActions">
              <button
                className={clsx("iconButton", (files?.length || url) && "iconButton--active")}
                type="button"
                onClick={() => setAttachOpen((o) => !o)}
                title="Attach files or URL"
              >
                <Paperclip size={15} />
              </button>
              <button className="secondaryButton" type="button" onClick={() => void loadDemoPacket()} disabled={busy === "demo"}>
                {busy === "demo" ? <Loader2 className="spin" size={13} /> : null}
                {UI_COPY.seedDemoButton}
              </button>
              <div className="spacer" />
              <button className="primaryButton" type="button" onClick={() => void analyzeDeal()} disabled={!canRunAgent}>
                {isAnalyzing ? <Loader2 className="spin" size={13} /> : <Bot size={13} />}
                {UI_COPY.runAgentButton}
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
    if (event.event !== "tool_start" && event.event !== "tool_complete") continue;
    const existing = tools.get(event.step);
    tools.set(event.step, {
      step: event.step,
      label: event.label,
      status: event.status,
      toolName: event.toolName ?? existing?.toolName,
      input: event.input ?? existing?.input,
      output: event.output ?? existing?.output,
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
      </dl>
    </details>
  );
}

function ResultArtifacts({
  deal,
  scoring,
  activeArtifact,
  selectedClaim,
  selectedEvidence,
  memoMarkdown,
  exportUrl,
  onOpenClaims,
  onOpenMemo,
  onSelectClaim,
  onUpdateClaimReview
}: {
  deal: DealAnalysis;
  scoring: ReturnType<typeof scoreClaims>;
  activeArtifact: ActiveArtifact;
  selectedClaim: DealClaim | null;
  selectedEvidence: EvidenceItem[];
  memoMarkdown: string;
  exportUrl: string;
  onOpenClaims: () => void;
  onOpenMemo: () => void;
  onSelectClaim: (claim: DealClaim) => void;
  onUpdateClaimReview: (claimId: string, payload: { status?: ClaimStatus; reviewerStatus?: DealClaim["reviewerStatus"]; reviewerNotes?: string }) => Promise<void>;
}) {
  const claims = deal.claims;
  if (!deal.materials.length) return null;

  return (
    <div>
      <div className="artifactGrid">
        <button className="artifactCard artifactButton" type="button" onClick={onOpenClaims} disabled={!claims.length}>
          <div className="artifactHeader">
            <Gauge size={16} />
            <strong>{UI_COPY.claimLedgerTitle}</strong>
            <span>{claims.length || UI_COPY.pending}</span>
          </div>
          <p>{claims.length ? `${scoring.counts.weak + scoring.counts.contradicted + scoring.counts.missing} ${UI_COPY.exceptionsNeedReview}` : UI_COPY.claimLedgerPending}</p>
        </button>
        <button className="artifactCard artifactButton" type="button" onClick={onOpenMemo} disabled={!deal.memo}>
          <div className="artifactHeader">
            <FileText size={16} />
            <strong>{UI_COPY.riskMemoTitle}</strong>
            <span>{deal.memo?.overallGrade ?? UI_COPY.pending}</span>
          </div>
          <p>{deal.memo ? deal.memo.icRecommendation : UI_COPY.riskMemoPending}</p>
        </button>
        {deal.qualityReview && (
          <div className="artifactCard">
            <div className="artifactHeader">
              <ClipboardCheck size={16} />
              <strong>Memo readiness</strong>
              <span>{deal.qualityReview.memoReadinessScore}%</span>
            </div>
            <p>{deal.qualityReview.globalWarnings[0] ?? "Quality review passed without global warnings."}</p>
          </div>
        )}
      </div>

      {activeArtifact?.type === "claims" && <ClaimsArtifact claims={claims} evidence={deal.evidence} onSelectClaim={onSelectClaim} />}
      {activeArtifact?.type === "claim" && selectedClaim && (
        <EvidenceArtifact key={selectedClaim.id} claim={selectedClaim} evidence={selectedEvidence} onUpdateClaimReview={onUpdateClaimReview} />
      )}
      {activeArtifact?.type === "memo" && deal.memo && <MemoArtifact deal={deal} memoMarkdown={memoMarkdown} exportUrl={exportUrl} />}
    </div>
  );
}

function ClaimsArtifact({ claims, evidence, onSelectClaim }: { claims: DealClaim[]; evidence: EvidenceItem[]; onSelectClaim: (claim: DealClaim) => void }) {
  const groups: ClaimStatus[] = ["contradicted", "weak", "missing", "supported"];
  return (
    <section className="artifactPanel">
      <div className="artifactPanelHeader">
        <h2>{claims.length} diligence claims</h2>
      </div>
      <div className="claimGroups">
        {groups.map((status) => {
          const items = claims.filter((claim) => claim.status === status);
          if (!items.length) return null;
          return (
            <section key={status} className="claimGroup">
              <h3>{status}</h3>
              {items.map((claim) => {
                const count = evidence.filter((item) => item.claimId === claim.id).length;
                return (
                  <button key={claim.id} type="button" className="claimRow" onClick={() => onSelectClaim(claim)}>
                    <StatusPill status={claim.status} />
                    <span>{claim.text}</span>
                    <small>{claim.confidence} confidence / {claim.qualityScore}% / {count} {UI_COPY.evidenceLabel}</small>
                    <PanelRightOpen size={14} />
                  </button>
                );
              })}
            </section>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceArtifact({
  claim,
  evidence,
  onUpdateClaimReview
}: {
  claim: DealClaim;
  evidence: EvidenceItem[];
  onUpdateClaimReview: (claimId: string, payload: { status?: ClaimStatus; reviewerStatus?: DealClaim["reviewerStatus"]; reviewerNotes?: string }) => Promise<void>;
}) {
  const [notes, setNotes] = useState(claim.reviewerNotes);
  const independentSourceCount = new Set(evidence.filter((item) => item.sourceIndependence === "third_party").map((item) => sourceLabel(item))).size;
  const strongestEvidence = primaryEvidence(evidence);
  return (
    <section className="artifactPanel">
      <div className="artifactPanelHeader">
        <h2>{claim.text}</h2>
        <StatusPill status={claim.status} />
      </div>
      <div className="qualityStrip">
        <Metric label="Confidence" value={claim.confidence} />
        <Metric label="Quality" value={`${claim.qualityScore}%`} />
        <Metric label="Decision impact" value={claim.decisionImpact} />
        <Metric label="Reviewer" value={claim.reviewerStatus.replaceAll("_", " ")} />
      </div>
      <div className="rationale">
        <AlertTriangle size={16} />
        <p>{claim.riskRationale} {claim.verificationNeed}</p>
      </div>
      <div className="citationSummary">
        <Metric label="Citations" value={`${evidence.length}`} />
        <Metric label="Independent" value={`${independentSourceCount}`} />
        <Metric label="Primary source" value={strongestEvidence ? sourceLabel(strongestEvidence) : "None"} />
      </div>
      {claim.qualityIssues.length > 0 && (
        <div className="qualityIssues">
          {claim.qualityIssues.map((issue) => (
            <span key={issue}>{issue}</span>
          ))}
        </div>
      )}
      <div className="reviewControls">
        <label>
          Status
          <select value={claim.status} onChange={(event) => void onUpdateClaimReview(claim.id, { status: event.target.value as ClaimStatus })}>
            {(["supported", "weak", "contradicted", "missing"] as ClaimStatus[]).map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </label>
        <button type="button" className="secondaryButton" onClick={() => void onUpdateClaimReview(claim.id, { reviewerStatus: "verified" })}>
          <CheckCircle2 size={13} />
          Mark verified
        </button>
        <button type="button" className="secondaryButton" onClick={() => void onUpdateClaimReview(claim.id, { reviewerStatus: "needs_evidence" })}>
          <MessageSquarePlus size={13} />
          Request evidence
        </button>
      </div>
      <form
        className="reviewNotes"
        onSubmit={(event) => {
          event.preventDefault();
          void onUpdateClaimReview(claim.id, { reviewerNotes: notes });
        }}
      >
        <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Reviewer note" />
        <button type="submit" className="secondaryButton">Save note</button>
      </form>
      <div className="evidenceList">
        {evidence.map((item) => (
          <article key={item.id} className={clsx("evidenceItem", `evidenceItem--${item.stance}`)}>
            <header className="citationHeader">
              <div className="citationTitle">
                <span>{item.stance.replaceAll("_", " ")}</span>
                <strong>{sourceLabel(item)}</strong>
                <small>{chunkLabel(item)}</small>
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
            {item.quoteSpan && item.snippet && item.snippet !== item.quoteSpan && <p className="contextSnippet">{item.snippet}</p>}
            <div className="citationReason">Used to {stanceVerb(item.stance)} this claim.</div>
            <footer className="citationMeta">
              <span>{item.citation}</span>
              <span>{item.sourceType.replace("_", " ")}</span>
              <span>{item.sourceIndependence.replace("_", " ")}</span>
              <span>{item.reliability} reliability</span>
              <span>{Math.round(item.relevanceScore * 100)}% relevance</span>
            </footer>
          </article>
        ))}
      </div>
    </section>
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

function MemoArtifact({ deal, memoMarkdown, exportUrl }: { deal: DealAnalysis; memoMarkdown: string; exportUrl: string }) {
  if (!deal.memo) return null;
  const memo = deal.memo;
  const risks = memo.keyRisks?.length ? memo.keyRisks : memo.materialRisks;
  const diligenceRequests = memo.nextDiligenceRequests?.length ? memo.nextDiligenceRequests : memo.followUpQuestions;
  return (
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
      <p className="memoQuestion">{memo.investmentQuestion}</p>
      {memo.decisionDrivers?.length ? <MemoSection title={UI_COPY.decisionDriversTitle} items={memo.decisionDrivers} /> : null}
      <div className="memoColumns">
        <MemoSection title={UI_COPY.keyStrengthsTitle} items={memo.keyStrengths} />
        <MemoSection title={UI_COPY.materialRisksTitle} items={risks} danger />
        <MemoSection title={UI_COPY.followUpQuestionsTitle} items={diligenceRequests} />
      </div>
      {memo.evidenceMap?.length ? <MemoSection title={UI_COPY.evidenceMapTitle} items={memo.evidenceMap} /> : null}
      <div className="recommendation">{memo.icRecommendation}</div>
      <details className="markdownDetails">
        <summary>{UI_COPY.markdownPreviewTitle}</summary>
        <pre>{memoMarkdown}</pre>
      </details>
    </section>
  );
}

function AnswerMessage({ answer }: { answer: ChatAnswer }) {
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

function chunkLabel(item: EvidenceItem) {
  if (item.chunkIndex) return `Chunk ${item.chunkIndex}`;
  const match = item.citation.match(/chunk\s+(\d+)/i);
  return match ? `Chunk ${match[1]}` : "Source excerpt";
}

function stanceVerb(stance: EvidenceItem["stance"]) {
  if (stance === "supports") return "support";
  if (stance === "contradicts") return "contradict";
  if (stance === "partially_supports") return "partially support";
  return "mark evidence as missing for";
}

function primaryEvidence(evidence: EvidenceItem[]) {
  const stanceRank: Record<EvidenceItem["stance"], number> = {
    supports: 4,
    contradicts: 3,
    partially_supports: 2,
    not_found: 1
  };
  return [...evidence].sort((a, b) => stanceRank[b.stance] - stanceRank[a.stance] || b.relevanceScore - a.relevanceScore)[0] ?? null;
}

function shortCitation(citation: string) {
  return citation.replace(/,\s*chunk\s*/i, " #");
}
