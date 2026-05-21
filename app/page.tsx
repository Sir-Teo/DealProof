"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  FileSearch,
  FileText,
  Gauge,
  Link,
  Loader2,
  MessageSquare,
  PanelRightOpen,
  Send,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";
import type { ChatAnswer, ClaimStatus, DealAnalysis, DealClaim, EvidenceItem } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const sampleQuestions = ["Can we trust the ROI claim?", "What should we ask before IC?", "Is the no competitor claim supported?"];
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
  const [company, setCompany] = useState("CaviClear AI");
  const [tagline, setTagline] = useState("AI billing automation for dental clinics");
  const [files, setFiles] = useState<FileList | null>(null);
  const [url, setUrl] = useState("");
  const [question, setQuestion] = useState(sampleQuestions[0]);
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<ActiveArtifact>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [feedNotes, setFeedNotes] = useState<FeedNote[]>([
    {
      id: "welcome",
      role: "agent",
      title: "Drop in a deal packet or seed the demo.",
      body: "DealProof will extract claims, check evidence, draft the memo, and keep the agent stream visible while it works."
    }
  ]);

  const claims = useMemo(() => deal?.claims ?? [], [deal?.claims]);
  const scoring = useMemo(() => (claims.length ? scoreClaims(claims) : { overall: 0, grade: "red" as const, counts: emptyCounts }), [claims]);
  const selectedClaim =
    activeArtifact?.type === "claim" ? claims.find((claim) => claim.id === activeArtifact.claimId) ?? claims[0] ?? null : claims[0] ?? null;
  const selectedEvidence = selectedClaim && deal ? evidenceForClaim(selectedClaim.id, deal.evidence) : [];
  const memoMarkdown = deal?.memo ? generateMemoMarkdown(deal.memo) : "";
  const exportUrl = deal ? `${API_BASE}/deals/${deal.id}/export-memo` : "#";
  const isAnalyzing = busy === "analyze";
  const canRunAgent = Boolean(deal?.materials.length) && !isAnalyzing;
  const materialCount = deal?.materials.length ?? 0;
  const evidenceCount = deal?.evidence.length ?? 0;

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, init);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
    }
    return (await response.json()) as T;
  }

  async function readAgentStream(response: Response, onEvent: (event: AgentEvent) => void) {
    if (!response.body) throw new Error("Streaming is not available in this browser.");
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
    setFeedNotes((notes) => [...notes, { ...note, id: `${Date.now()}-${notes.length}` }]);
  }

  async function ensureDeal() {
    if (deal) return deal;
    const created = await api<DealAnalysis>("/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company, tagline, stage: "Active diligence" })
    });
    setDeal(created);
    setAgentEvents([]);
    setAnswer(null);
    addFeedNote({ role: "user", title: `Created ${created.company}`, body: created.tagline });
    return created;
  }

  async function createDeal(event?: FormEvent) {
    event?.preventDefault();
    setBusy("create");
    setError(null);
    try {
      const created = await api<DealAnalysis>("/deals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company, tagline, stage: "Active diligence" })
      });
      setDeal(created);
      setAnswer(null);
      setAgentEvents([]);
      setActiveArtifact(null);
      setSettingsOpen(false);
      addFeedNote({ role: "user", title: `Created ${created.company}`, body: created.tagline });
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function loadDemoPacket() {
    setBusy("demo");
    setError(null);
    try {
      const created = await api<DealAnalysis>("/deals/demo", { method: "POST" });
      setDeal(created);
      setCompany(created.company);
      setTagline(created.tagline);
      setAnswer(null);
      setAgentEvents([]);
      setActiveArtifact(null);
      addFeedNote({ role: "user", title: "Seeded the CaviClear demo packet", body: `${created.materials.length} source materials loaded.` });
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
        title: "Added diligence material",
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
    addFeedNote({ role: "user", title: "Run the diligence agent", body: `${deal.materials.length} materials queued for analysis.` });
    try {
      const response = await fetch(`${API_BASE}/deals/${deal.id}/analyze-stream`, { method: "POST" });
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
        title: "Analysis complete",
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

  return (
    <main className="chatShell">
      <header className="appHeader">
        <div className="brandLine">
          <span className="brandMark">
            <ShieldCheck size={18} />
          </span>
          <div>
            <strong>DealProof</strong>
            <span>{deal?.company ?? "No deal loaded"}</span>
          </div>
        </div>
        <div className="headerStats" aria-label="Deal status">
          <span>{deal?.status.replace("_", " ") ?? "Backend required"}</span>
          <span>{materialCount} materials</span>
          <span>{claims.length ? `${scoring.grade.toUpperCase()} risk ${scoring.overall}` : "No analysis"}</span>
        </div>
      </header>

      <section className="feedWrap">
        <div className="messageFeed" aria-live="polite">
          {error && (
            <article className="systemBanner errorBanner">
              <XCircle size={16} />
              <span>{error}</span>
            </article>
          )}

          {feedNotes.map((note) => (
            <ChatBubble key={note.id} role={note.role} title={note.title} body={note.body} />
          ))}

          {(isAnalyzing || agentEvents.length > 0) && <AgentActivity events={agentEvents} running={isAnalyzing} />}

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
            />
          )}

          {busy === "chat" && (
            <article className="message agentMessage">
              <Avatar status="running" />
              <div className="messageBody">
                <div className="messageMeta">
                  <strong>DealProof</strong>
                  <span>Answering</span>
                </div>
                <p className="messageTitle">Checking stored claims and evidence.</p>
              </div>
            </article>
          )}

          {answer && <AnswerMessage answer={answer} />}
        </div>
      </section>

      <form className="composer" onSubmit={(event) => { event.preventDefault(); void askQuestion(); }}>
        <div className="composerInner">
          <button className="ghostButton" type="button" onClick={() => setSettingsOpen((open) => !open)} aria-expanded={settingsOpen}>
            Deal settings
            <ChevronDown size={15} />
          </button>
          {settingsOpen && (
            <div className="settingsPanel">
              <label>
                Company
                <input value={company} onChange={(event) => setCompany(event.target.value)} />
              </label>
              <label>
                Tagline
                <input value={tagline} onChange={(event) => setTagline(event.target.value)} />
              </label>
              <button className="secondaryButton" type="button" onClick={() => void createDeal()} disabled={busy === "create"}>
                Create Deal
              </button>
            </div>
          )}

          <div className="sourceRow">
            <button className="secondaryButton" type="button" onClick={() => void loadDemoPacket()} disabled={busy === "demo"}>
              {busy === "demo" ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
              Seed demo
            </button>
            <label className="fileButton">
              <Upload size={16} />
              Upload
              <input
                type="file"
                multiple
                accept=".pdf,.txt,.csv,.docx"
                onChange={(event: ChangeEvent<HTMLInputElement>) => setFiles(event.target.files)}
              />
            </label>
            <div className="urlField">
              <Link size={15} />
              <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Add URL" />
            </div>
            <button className="secondaryButton" type="button" onClick={() => void uploadMaterials()} disabled={busy === "upload" || (!files?.length && !url.trim())}>
              {busy === "upload" ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
              Add
            </button>
            <button className="primaryButton" type="button" onClick={() => void analyzeDeal()} disabled={!canRunAgent}>
              {isAnalyzing ? <Loader2 className="spin" size={16} /> : <Bot size={16} />}
              Run agent
            </button>
          </div>

          <div className="promptRow">
            <MessageSquare size={17} />
            <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about the deal evidence..." disabled={!deal} />
            <button className="sendButton" type="submit" disabled={!deal || busy === "chat"}>
              {busy === "chat" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              <span>Ask</span>
            </button>
          </div>
          <div className="sampleQuestions">
            {sampleQuestions.map((item) => (
              <button key={item} type="button" onClick={() => void askQuestion(item)} disabled={!deal?.claims.length}>
                {item}
              </button>
            ))}
          </div>
        </div>
      </form>
    </main>
  );
}

function ChatBubble({ role, title, body }: Omit<FeedNote, "id">) {
  return (
    <article className={clsx("message", role === "user" ? "userMessage" : "agentMessage")}>
      <Avatar status={role === "user" ? "user" : "done"} />
      <div className="messageBody">
        <div className="messageMeta">
          <strong>{role === "user" ? "You" : "DealProof"}</strong>
        </div>
        <p className="messageTitle">{title}</p>
        {body && <p className="messageCopy">{body}</p>}
      </div>
    </article>
  );
}

function Avatar({ status }: { status: AgentEventStatus | "user" }) {
  return (
    <div className={clsx("avatar", status)}>
      {status === "running" ? <Loader2 className="spin" size={15} /> : status === "error" ? <XCircle size={15} /> : status === "user" ? <MessageSquare size={15} /> : <Bot size={15} />}
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
  const activityLabel = latestProgress?.label ?? "Preparing analysis";

  return (
    <article className="message agentMessage">
      <Avatar status={activityStatus} />
      <div className="messageBody agentStream">
        <div className="messageMeta">
          <strong>DealProof</strong>
          <span>{activityStatus === "running" ? "Working" : activityStatus === "error" ? "Stopped" : "Finished"}</span>
        </div>
        <p className="messageTitle">{activityLabel}</p>
        <small>{latestProgress ? formatAgentStats(latestProgress) : "Working"}</small>
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
          <dt>Input</dt>
          <dd>{tool.input ?? "state"}</dd>
        </div>
        <div>
          <dt>Output</dt>
          <dd>{tool.output ?? "Waiting for result"}</dd>
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
  onSelectClaim
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
}) {
  const claims = deal.claims;
  if (!deal.materials.length) {
    return (
      <article className="artifactCard">
        <div className="artifactHeader">
          <FileText size={17} />
          <strong>No materials yet</strong>
        </div>
        <p>Add files, a URL, or seed the demo packet to start the diligence run.</p>
      </article>
    );
  }

  return (
    <article className="message agentMessage">
      <Avatar status="done" />
      <div className="messageBody">
        <div className="messageMeta">
          <strong>Artifacts</strong>
          <span>{deal.materials.length} materials / {claims.length} claims / {deal.evidence.length} evidence</span>
        </div>
        <div className="artifactGrid">
          <button className="artifactCard artifactButton" type="button" onClick={onOpenClaims} disabled={!claims.length}>
            <div className="artifactHeader">
              <Gauge size={17} />
              <strong>Claim ledger</strong>
              <span>{claims.length || "Pending"}</span>
            </div>
            <p>{claims.length ? `${scoring.counts.weak + scoring.counts.contradicted + scoring.counts.missing} exceptions need review.` : "Run the agent to extract verifiable claims."}</p>
          </button>
          <button className="artifactCard artifactButton" type="button" onClick={onOpenMemo} disabled={!deal.memo}>
            <div className="artifactHeader">
              <FileText size={17} />
              <strong>Risk memo</strong>
              <span>{deal.memo?.overallGrade ?? "Pending"}</span>
            </div>
            <p>{deal.memo ? deal.memo.icRecommendation : "The memo appears after analysis completes."}</p>
          </button>
        </div>

        {activeArtifact?.type === "claims" && <ClaimsArtifact claims={claims} evidence={deal.evidence} onSelectClaim={onSelectClaim} />}
        {activeArtifact?.type === "claim" && selectedClaim && <EvidenceArtifact claim={selectedClaim} evidence={selectedEvidence} />}
        {activeArtifact?.type === "memo" && deal.memo && <MemoArtifact deal={deal} memoMarkdown={memoMarkdown} exportUrl={exportUrl} />}
      </div>
    </article>
  );
}

function ClaimsArtifact({ claims, evidence, onSelectClaim }: { claims: DealClaim[]; evidence: EvidenceItem[]; onSelectClaim: (claim: DealClaim) => void }) {
  const groups: ClaimStatus[] = ["contradicted", "weak", "missing", "supported"];
  return (
    <section className="artifactPanel">
      <div className="artifactPanelHeader">
        <div>
          <p className="eyebrow">Claim Ledger</p>
          <h2>{claims.length} diligence claims</h2>
        </div>
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
                    <small>{claim.importance} / {count} evidence</small>
                    <PanelRightOpen size={15} />
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

function EvidenceArtifact({ claim, evidence }: { claim: DealClaim; evidence: EvidenceItem[] }) {
  return (
    <section className="artifactPanel">
      <div className="artifactPanelHeader">
        <div>
          <p className="eyebrow">Evidence Drawer</p>
          <h2>{claim.text}</h2>
        </div>
        <StatusPill status={claim.status} />
      </div>
      <div className="rationale">
        <AlertTriangle size={17} />
        <p>{claim.riskRationale}</p>
      </div>
      <div className="evidenceList">
        {evidence.map((item) => (
          <article key={item.id} className="evidenceItem">
            <div>
              <strong>{item.title}</strong>
              <span>{item.stance.replaceAll("_", " ")}</span>
            </div>
            <p>{item.snippet}</p>
            <footer>
              <span>{item.citation}</span>
              <span>{item.sourceType.replace("_", " ")}</span>
              <span>{item.reliability} reliability</span>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}

function MemoArtifact({ deal, memoMarkdown, exportUrl }: { deal: DealAnalysis; memoMarkdown: string; exportUrl: string }) {
  if (!deal.memo) return null;
  return (
    <section className="artifactPanel memoArtifact">
      <div className="artifactPanelHeader">
        <div>
          <p className="eyebrow">IC Artifact</p>
          <h2>Partner-ready red team memo</h2>
        </div>
        <a className="primaryButton" href={exportUrl}>
          <ArrowDownToLine size={16} />
          Export Markdown
        </a>
      </div>
      <p className="memoQuestion">{deal.memo.investmentQuestion}</p>
      <div className="memoColumns">
        <MemoSection title="Key strengths" items={deal.memo.keyStrengths} />
        <MemoSection title="Material risks" items={deal.memo.materialRisks} danger />
        <MemoSection title="Questions before IC" items={deal.memo.followUpQuestions} />
      </div>
      <div className="recommendation">{deal.memo.icRecommendation}</div>
      <details className="markdownDetails">
        <summary>Markdown preview</summary>
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
          <strong>DealProof answer</strong>
          <span>{answer.confidence} confidence</span>
        </div>
        <p className="messageCopy">{answer.answer}</p>
        <footer>
          {answer.citations.map((citation) => (
            <span key={citation}>{citation}</span>
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
      <Icon size={14} />
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
  if (event.status === "error") return "Needs attention";
  return stats.join(" / ") || (event.status === "done" ? "Complete" : "Working");
}
