export type ClaimStatus = "supported" | "weak" | "contradicted" | "missing";
export type Confidence = "high" | "medium" | "low";
export type ReviewerStatus = "unreviewed" | "verified" | "needs_evidence";
export type ReviewerDisposition = "unreviewed" | "verified" | "needs_evidence" | "ignored" | "ic_blocker";
export type ScoreGrade = "green" | "yellow" | "red";
export type ReadinessStatus = "ic_ready" | "needs_diligence" | "blocked" | "screen_out";

export type DealClaim = {
  id: string;
  text: string;
  category:
    | "market"
    | "growth"
    | "customer_roi"
    | "competition"
    | "pricing"
    | "retention"
    | "compliance"
    | "financials"
    | "product"
    | "team"
    | "go_to_market"
    | "fundraising"
    | "legal"
    | "operations";
  sourceMaterial: string;
  sourceSnippet: string;
  importance: "high" | "medium" | "low";
  status: ClaimStatus;
  riskRationale: string;
  confidence: Confidence;
  qualityScore: number;
  qualityIssues: string[];
  verificationNeed: string;
  decisionImpact: "high" | "medium" | "low";
  reviewerStatus: ReviewerStatus;
  reviewerDisposition: ReviewerDisposition;
  reviewerNotes: string;
  statusReason: string;
  resolutionRequest: string;
};

export type EvidenceItem = {
  id: string;
  claimId: string;
  title: string;
  sourceType: "uploaded" | "supplied_url" | "public_web" | "derived";
  citation: string;
  snippet: string;
  stance: "supports" | "partially_supports" | "contradicts" | "not_found";
  reliability: "high" | "medium" | "low";
  sourceIndependence: "founder_supplied" | "internal" | "third_party" | "derived";
  relevanceScore: number;
  quoteSpan?: string | null;
  sourceMaterialId?: string | null;
  sourceName?: string | null;
  sourceUrl?: string | null;
  chunkIndex?: number | null;
  retrievedAt?: string | null;
};

export type RiskMemo = {
  company: string;
  overallGrade: ScoreGrade;
  investmentQuestion: string;
  keyStrengths: string[];
  materialRisks: string[];
  followUpQuestions: string[];
  icRecommendation: string;
  executiveSummary?: string;
  thesisAssessment?: string;
  evidenceMap?: string[];
  keyRisks?: string[];
  nextDiligenceRequests?: string[];
  decisionDrivers?: string[];
};

export type DealProfile = {
  sector: string;
  businessModel: string;
  customer: string;
  stage: string;
  materialMix: string[];
};

export type QualityReview = {
  memoReadinessScore: number;
  globalWarnings: string[];
  duplicatedClaims: string[];
  lowValueClaims: string[];
  recommendedFollowUpEvidence: string[];
  overconfidenceWarnings: string[];
  readinessStatus: ReadinessStatus;
  topGatingIssue: string;
  approvedDiligenceRequests: string[];
};

export type ScoreSummary = {
  overall: number;
  grade: ScoreGrade;
  counts: Record<ClaimStatus, number>;
  drivers: string[];
};

export type ChatTurn = {
  id: string;
  dealId: string;
  question: string;
  answer: string;
  citations: string[];
  confidence: "high" | "medium" | "low";
  createdAt: string;
};

export type SourceMaterial = {
  id: string;
  deal_id?: string;
  name: string;
  kind: "deck" | "transcript" | "financials" | "url" | "document";
  source_type?: "file" | "url" | "seed";
  pages?: number;
  summary: string;
  excerpt: string;
  text?: string;
};

export type DealAnalysis = {
  id: string;
  company: string;
  tagline: string;
  stage: string;
  status: "draft" | "materials_loaded" | "running" | "completed" | "failed";
  error?: string | null;
  materials: SourceMaterial[];
  claims: DealClaim[];
  evidence: EvidenceItem[];
  profile: DealProfile | null;
  memo: RiskMemo | null;
  qualityReview: QualityReview | null;
  score: ScoreSummary | null;
  generatedAt: string | null;
  chatHistory: ChatTurn[];
};

export type ChatAnswer = {
  answer: string;
  citations: string[];
  confidence: "high" | "medium" | "low";
};
