"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  Bot,
  CheckCircle2,
  CircleHelp,
  ClipboardList,
  FileSearch,
  FileText,
  Gauge,
  Link,
  Loader2,
  MessageSquare,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";
import type { ChatAnswer, ClaimStatus, DealAnalysis, DealClaim, SourceMaterial } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const tabs = [
  { id: "upload", label: "Upload", icon: Upload },
  { id: "claims", label: "Claims", icon: ClipboardList },
  { id: "evidence", label: "Evidence", icon: FileSearch },
  { id: "memo", label: "Risk Memo", icon: FileText },
  { id: "chat", label: "Q&A", icon: MessageSquare }
] as const;

type TabId = (typeof tabs)[number]["id"];

const statusIcon: Record<ClaimStatus, typeof CheckCircle2> = {
  supported: CheckCircle2,
  weak: AlertTriangle,
  contradicted: XCircle,
  missing: CircleHelp
};

const emptyCounts = { supported: 0, weak: 0, contradicted: 0, missing: 0 };
const sampleQuestions = ["Can we trust the ROI claim?", "What should we ask before IC?", "Is the no competitor claim supported?"];

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("upload");
  const [deal, setDeal] = useState<DealAnalysis | null>(null);
  const [company, setCompany] = useState("CaviClear AI");
  const [tagline, setTagline] = useState("AI billing automation for dental clinics");
  const [files, setFiles] = useState<FileList | null>(null);
  const [url, setUrl] = useState("");
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [question, setQuestion] = useState(sampleQuestions[0]);
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const claims = useMemo(() => deal?.claims ?? [], [deal?.claims]);
  const selectedClaim = claims.find((claim) => claim.id === selectedClaimId) ?? claims[0] ?? null;
  const selectedEvidence = selectedClaim && deal ? evidenceForClaim(selectedClaim.id, deal.evidence) : [];
  const scoring = useMemo(() => (claims.length ? scoreClaims(claims) : { overall: 0, grade: "red" as const, counts: emptyCounts }), [claims]);
  const memoMarkdown = deal?.memo ? generateMemoMarkdown(deal.memo) : "";
  const exportUrl = deal ? `${API_BASE}/deals/${deal.id}/export-memo` : "#";

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, init);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
    }
    return (await response.json()) as T;
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
      setSelectedClaimId(null);
      setAnswer(null);
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
      setSelectedClaimId(null);
      setAnswer(null);
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  async function uploadMaterials(event: FormEvent) {
    event.preventDefault();
    if (!deal) {
      await createDeal();
      return;
    }
    setBusy("upload");
    setError(null);
    try {
      const form = new FormData();
      Array.from(files ?? []).forEach((file) => form.append("files", file));
      if (url.trim()) form.append("url", url.trim());
      const updated = await api<DealAnalysis>(`/deals/${deal.id}/materials`, { method: "POST", body: form });
      setDeal(updated);
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
    try {
      const analyzed = await api<DealAnalysis>(`/deals/${deal.id}/analyze`, { method: "POST" });
      setDeal(analyzed);
      setSelectedClaimId(analyzed.claims[0]?.id ?? null);
      setActiveTab("claims");
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
    setQuestion(nextQuestion);
    setBusy("chat");
    setAnswer(null);
    setError(null);
    try {
      setAnswer(
        await api<ChatAnswer>(`/deals/${deal.id}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: nextQuestion })
        })
      );
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Deal navigation">
        <div className="brand">
          <div className="brandMark">
            <ShieldCheck size={22} />
          </div>
          <div>
            <p className="eyebrow">DealProof</p>
            <h1>AI diligence red team</h1>
          </div>
        </div>

        <div className="dealCard">
          <p className="eyebrow">Active Deal</p>
          <h2>{deal?.company ?? "No deal loaded"}</h2>
          <p>{deal?.tagline ?? "Create a deal, upload materials, then run the agent."}</p>
          <span>{deal ? `${deal.stage} · ${deal.status}` : "FastAPI backend required"}</span>
        </div>

        <nav className="tabs">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={clsx("tabButton", activeTab === tab.id && "active")}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                <Icon size={18} />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Python LangGraph + DeepSeek</p>
            <h2>Pressure-test founder claims before IC</h2>
          </div>
          <div className="scorePanel">
            <Gauge size={19} />
            <span>{scoring.overall}</span>
            <small>{claims.length ? `${scoring.grade.toUpperCase()} risk grade` : "No analysis yet"}</small>
          </div>
        </header>

        {error && <div className="errorBanner">{error}</div>}

        <section className="metrics" aria-label="Claim status summary">
          <Metric label="Supported" value={scoring.counts.supported} status="supported" />
          <Metric label="Weak" value={scoring.counts.weak} status="weak" />
          <Metric label="Contradicted" value={scoring.counts.contradicted} status="contradicted" />
          <Metric label="Missing evidence" value={scoring.counts.missing} status="missing" />
        </section>

        {activeTab === "upload" && (
          <section className="panel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Real ingestion</p>
                <h3>Upload files or seed the demo packet</h3>
              </div>
              <button className="primaryButton" type="button" onClick={() => void analyzeDeal()} disabled={!deal || !deal.materials.length || busy === "analyze"}>
                {busy === "analyze" ? <Loader2 className="spin" size={17} /> : <Bot size={17} />}
                Run LangGraph Agent
              </button>
            </div>

            <form className="dealForm" onSubmit={createDeal}>
              <label>
                Company
                <input value={company} onChange={(event) => setCompany(event.target.value)} />
              </label>
              <label>
                Tagline
                <input value={tagline} onChange={(event) => setTagline(event.target.value)} />
              </label>
              <button className="secondaryButton" type="submit" disabled={busy === "create"}>
                Create Deal
              </button>
              <button className="primaryButton" type="button" onClick={() => void loadDemoPacket()} disabled={busy === "demo"}>
                {busy === "demo" ? <Loader2 className="spin" size={17} /> : <Upload size={17} />}
                Seed CaviClear Packet
              </button>
            </form>

            <form className="uploadZone realUpload" onSubmit={uploadMaterials}>
              <Upload size={30} />
              <div>
                <strong>{deal ? "Add diligence materials" : "Create a deal first"}</strong>
                <p>Supports PDF, TXT, CSV, DOCX, plus supplied URLs. Public verification is limited to supplied URLs until a search provider is added.</p>
                <div className="uploadControls">
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.txt,.csv,.docx"
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setFiles(event.target.files)}
                    disabled={!deal}
                  />
                  <div className="urlInput">
                    <Link size={16} />
                    <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://company.com or source URL" disabled={!deal} />
                  </div>
                  <button className="secondaryButton" type="submit" disabled={!deal || busy === "upload"}>
                    Add Materials
                  </button>
                </div>
              </div>
            </form>

            <MaterialGrid materials={deal?.materials ?? []} />
          </section>
        )}

        {activeTab === "claims" && (
          claims.length ? (
            <section className="split">
              <ClaimTable claims={claims} selectedClaimId={selectedClaim?.id ?? ""} onSelect={(claim) => setSelectedClaimId(claim.id)} />
              {selectedClaim && <ClaimInspector claim={selectedClaim} />}
            </section>
          ) : (
            <EmptyPanel title="No claims yet" body="Upload materials and run the LangGraph agent to extract claim-level diligence." />
          )
        )}

        {activeTab === "evidence" && (
          claims.length && selectedClaim ? (
            <section className="split">
              <ClaimTable claims={claims} selectedClaimId={selectedClaim.id} onSelect={(claim) => setSelectedClaimId(claim.id)} />
              <section className="panel detailPanel">
                <div className="panelHeader">
                  <div>
                    <p className="eyebrow">Evidence drawer</p>
                    <h3>{selectedClaim.text}</h3>
                  </div>
                  <StatusPill status={selectedClaim.status} />
                </div>
                <div className="evidenceList">
                  {selectedEvidence.map((item) => (
                    <article key={item.id} className="evidenceItem">
                      <div>
                        <strong>{item.title}</strong>
                        <StatusDot label={item.stance.replaceAll("_", " ")} status={selectedClaim.status} />
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
            </section>
          ) : (
            <EmptyPanel title="No evidence yet" body="Evidence is generated during the backend analysis run." />
          )
        )}

        {activeTab === "memo" && (
          deal?.memo ? (
            <section className="panel memoPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Partner-ready export</p>
                  <h3>1-page IC red team memo</h3>
                </div>
                <a className="primaryButton" href={exportUrl}>
                  <ArrowDownToLine size={17} />
                  Export Markdown
                </a>
              </div>
              <div className="memoLayout">
                <article className="memoPreview">
                  <div className="memoTitle">
                    <span className={clsx("gradeBadge", deal.memo.overallGrade)}>{deal.memo.overallGrade}</span>
                    <h2>{deal.memo.company}</h2>
                  </div>
                  <p className="memoQuestion">{deal.memo.investmentQuestion}</p>
                  <MemoSection title="Key strengths" items={deal.memo.keyStrengths} />
                  <MemoSection title="Material risks" items={deal.memo.materialRisks} danger />
                  <MemoSection title="Questions before IC" items={deal.memo.followUpQuestions} />
                  <div className="recommendation">{deal.memo.icRecommendation}</div>
                </article>
                <pre className="markdownBox">{memoMarkdown}</pre>
              </div>
            </section>
          ) : (
            <EmptyPanel title="No memo yet" body="Run analysis to generate the IC red-team memo from extracted claims and evidence." />
          )
        )}

        {activeTab === "chat" && (
          <section className="panel chatPanel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Diligence Q&A</p>
                <h3>Ask against stored claims and evidence</h3>
              </div>
              <span className="modelBadge">DeepSeek via Python LangGraph backend</span>
            </div>
            <div className="promptRow">
              <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Diligence question" disabled={!deal?.claims.length} />
              <button className="primaryButton" type="button" onClick={() => void askQuestion()} disabled={!deal?.claims.length || busy === "chat"}>
                {busy === "chat" ? <Loader2 className="spin" size={17} /> : <MessageSquare size={17} />}
                {busy === "chat" ? "Asking" : "Ask"}
              </button>
            </div>
            <div className="sampleQuestions">
              {sampleQuestions.map((item) => (
                <button key={item} type="button" onClick={() => void askQuestion(item)} disabled={!deal?.claims.length}>
                  {item}
                </button>
              ))}
            </div>
            <article className="answerBox">
              {answer ? (
                <>
                  <div>
                    <Bot size={20} />
                    <strong>DealProof answer</strong>
                    <span>{answer.confidence} confidence</span>
                  </div>
                  <p>{answer.answer}</p>
                  <footer>{answer.citations.map((citation) => <span key={citation}>{citation}</span>)}</footer>
                </>
              ) : (
                <p>Run an analysis, then ask whether a claim is supported, what to ask next, or where the memo is most exposed.</p>
              )}
            </article>
          </section>
        )}
      </section>
    </main>
  );
}

function MaterialGrid({ materials }: { materials: SourceMaterial[] }) {
  if (!materials.length) return <EmptyPanel title="No materials loaded" body="Create a deal and add files, URLs, or the seeded CaviClear demo packet." compact />;
  return (
    <div className="materialGrid">
      {materials.map((material) => (
        <article key={material.id} className="material">
          <div>
            <FileText size={18} />
            <strong>{material.name}</strong>
          </div>
          <p>{material.summary}</p>
          <blockquote>{material.excerpt}</blockquote>
        </article>
      ))}
    </div>
  );
}

function EmptyPanel({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return (
    <section className={clsx("panel emptyPanel", compact && "compact")}>
      <h3>{title}</h3>
      <p>{body}</p>
    </section>
  );
}

function Metric({ label, value, status }: { label: string; value: number; status: ClaimStatus }) {
  return (
    <article className={clsx("metric", status)}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StatusPill({ status }: { status: ClaimStatus }) {
  const Icon = statusIcon[status];
  return (
    <span className={clsx("statusPill", status)}>
      <Icon size={15} />
      {status}
    </span>
  );
}

function StatusDot({ label, status }: { label: string; status: ClaimStatus }) {
  return <span className={clsx("statusDot", status)}>{label}</span>;
}

function ClaimTable({ claims, selectedClaimId, onSelect }: { claims: DealClaim[]; selectedClaimId: string; onSelect: (claim: DealClaim) => void }) {
  return (
    <section className="panel tablePanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Extracted claims</p>
          <h3>{claims.length} diligence claims</h3>
        </div>
      </div>
      <div className="claimRows">
        {claims.map((claim) => (
          <button key={claim.id} className={clsx("claimRow", selectedClaimId === claim.id && "selected")} type="button" onClick={() => onSelect(claim)}>
            <span>{claim.category.replace("_", " ")}</span>
            <strong>{claim.text}</strong>
            <StatusPill status={claim.status} />
          </button>
        ))}
      </div>
    </section>
  );
}

function ClaimInspector({ claim }: { claim: DealClaim }) {
  return (
    <section className="panel detailPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Risk rationale</p>
          <h3>{claim.text}</h3>
        </div>
        <StatusPill status={claim.status} />
      </div>
      <dl className="claimFacts">
        <div>
          <dt>Importance</dt>
          <dd>{claim.importance}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{claim.sourceMaterial}</dd>
        </div>
        <div>
          <dt>Snippet</dt>
          <dd>{claim.sourceSnippet}</dd>
        </div>
      </dl>
      <div className="rationale">
        <AlertTriangle size={18} />
        <p>{claim.riskRationale}</p>
      </div>
    </section>
  );
}

function MemoSection({ title, items, danger = false }: { title: string; items: string[]; danger?: boolean }) {
  return (
    <section className={clsx("memoSection", danger && "danger")}>
      <h4>{title}</h4>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}
