"use client";

import { useMemo, useState } from "react";
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
  MessageSquare,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import clsx from "clsx";
import { demoAnalysis } from "@/lib/demo-data";
import { evidenceForClaim, generateMemoMarkdown, scoreClaims } from "@/lib/scoring";
import type { ChatAnswer, ClaimStatus, DealClaim } from "@/lib/types";

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

const sampleQuestions = [
  "Can we trust the ROI claim?",
  "What should we ask before IC?",
  "Is the no competitor claim supported?"
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("upload");
  const [selectedClaimId, setSelectedClaimId] = useState(demoAnalysis.claims[0].id);
  const [question, setQuestion] = useState(sampleQuestions[0]);
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const analysis = demoAnalysis;
  const selectedClaim = analysis.claims.find((claim) => claim.id === selectedClaimId) ?? analysis.claims[0];
  const selectedEvidence = evidenceForClaim(selectedClaim.id, analysis.evidence);
  const scoring = useMemo(() => scoreClaims(analysis.claims), [analysis.claims]);
  const memoMarkdown = useMemo(() => generateMemoMarkdown(analysis.memo), [analysis.memo]);

  async function askQuestion(nextQuestion = question) {
    setQuestion(nextQuestion);
    setIsAsking(true);
    setAnswer(null);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: nextQuestion })
      });
      setAnswer((await response.json()) as ChatAnswer);
    } finally {
      setIsAsking(false);
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
          <h2>{analysis.company}</h2>
          <p>{analysis.tagline}</p>
          <span>{analysis.stage}</span>
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
            <p className="eyebrow">Raylu Build & Pitch demo</p>
            <h2>Pressure-test founder claims before IC</h2>
          </div>
          <div className="scorePanel">
            <Gauge size={19} />
            <span>{scoring.overall}</span>
            <small>{scoring.grade.toUpperCase()} risk grade</small>
          </div>
        </header>

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
                <p className="eyebrow">Demo packet</p>
                <h3>Messy materials in, claim ledger out</h3>
              </div>
              <button className="primaryButton" type="button" onClick={() => setActiveTab("claims")}>
                <Bot size={17} />
                Analyze Packet
              </button>
            </div>
            <div className="uploadZone">
              <Upload size={30} />
              <div>
                <strong>Gold-path demo loaded</strong>
                <p>Deck, founder transcript, financial snapshot, and website capture are staged for the live demo.</p>
              </div>
            </div>
            <div className="materialGrid">
              {analysis.materials.map((material) => (
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
          </section>
        )}

        {activeTab === "claims" && (
          <section className="split">
            <ClaimTable
              claims={analysis.claims}
              selectedClaimId={selectedClaim.id}
              onSelect={(claim) => setSelectedClaimId(claim.id)}
            />
            <ClaimInspector claim={selectedClaim} />
          </section>
        )}

        {activeTab === "evidence" && (
          <section className="split">
            <ClaimTable
              claims={analysis.claims}
              selectedClaimId={selectedClaim.id}
              onSelect={(claim) => setSelectedClaimId(claim.id)}
            />
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
        )}

        {activeTab === "memo" && (
          <section className="panel memoPanel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Partner-ready export</p>
                <h3>1-page IC red team memo</h3>
              </div>
              <a className="primaryButton" href="/api/export-memo">
                <ArrowDownToLine size={17} />
                Export Markdown
              </a>
            </div>
            <div className="memoLayout">
              <article className="memoPreview">
                <div className="memoTitle">
                  <span className={clsx("gradeBadge", analysis.memo.overallGrade)}>{analysis.memo.overallGrade}</span>
                  <h2>{analysis.memo.company}</h2>
                </div>
                <p className="memoQuestion">{analysis.memo.investmentQuestion}</p>
                <MemoSection title="Key strengths" items={analysis.memo.keyStrengths} />
                <MemoSection title="Material risks" items={analysis.memo.materialRisks} danger />
                <MemoSection title="Questions before IC" items={analysis.memo.followUpQuestions} />
                <div className="recommendation">{analysis.memo.icRecommendation}</div>
              </article>
              <pre className="markdownBox">{memoMarkdown}</pre>
            </div>
          </section>
        )}

        {activeTab === "chat" && (
          <section className="panel chatPanel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Diligence Q&A</p>
                <h3>Ask against claims and evidence</h3>
              </div>
              <span className="modelBadge">DeepSeek optional, fixture fallback</span>
            </div>
            <div className="promptRow">
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                aria-label="Diligence question"
              />
              <button className="primaryButton" type="button" onClick={() => void askQuestion()} disabled={isAsking}>
                <MessageSquare size={17} />
                {isAsking ? "Asking" : "Ask"}
              </button>
            </div>
            <div className="sampleQuestions">
              {sampleQuestions.map((item) => (
                <button key={item} type="button" onClick={() => void askQuestion(item)}>
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
                <p>Ask whether a claim is supported, what the partner should ask next, or where the memo is most exposed.</p>
              )}
            </article>
          </section>
        )}
      </section>
    </main>
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

function ClaimTable({
  claims,
  selectedClaimId,
  onSelect
}: {
  claims: DealClaim[];
  selectedClaimId: string;
  onSelect: (claim: DealClaim) => void;
}) {
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
          <button
            key={claim.id}
            className={clsx("claimRow", selectedClaimId === claim.id && "selected")}
            type="button"
            onClick={() => onSelect(claim)}
          >
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
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
