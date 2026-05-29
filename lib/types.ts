export type ClaimStatus = "supported" | "weak" | "contradicted" | "missing";
export type Confidence = "high" | "medium" | "low";
export type ReviewerStatus = "unreviewed" | "verified" | "needs_evidence";
export type ReviewerDisposition = "unreviewed" | "verified" | "needs_evidence" | "ignored" | "ic_blocker";
export type ScoreGrade = "green" | "yellow" | "red";
export type ReadinessStatus = "ic_ready" | "needs_diligence" | "blocked" | "screen_out";
export type ClaimKind =
  | "metric"
  | "customer"
  | "market"
  | "competition"
  | "product"
  | "compliance"
  | "financial"
  | "team"
  | "fundraising"
  | "legal"
  | "operational"
  | "other";
export type VerificationStandard =
  | "founder_statement"
  | "internal_document"
  | "customer_reference"
  | "third_party"
  | "audited_financials"
  | "legal_document"
  | "public_filing";
export type ReviewPriority = "critical" | "high" | "medium" | "low";
export type EvidenceRole = "primary_support" | "corroborating_support" | "contradiction" | "context" | "gap";
export type SourceAuthority = "founder" | "internal_operating" | "customer" | "third_party" | "public_filing" | "press" | "derived";
export type DeepSeekModelName = "deepseek-v4-flash" | "deepseek-v4-pro";

export type AppSettings = {
  maxClaims: number;
  maxClaimsPerMaterial: number;
  deepseekModel: DeepSeekModelName;
  webResearchEnabled: boolean;
};

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
  claimKind?: ClaimKind;
  extractedFact?: string;
  sourceLocator?: string;
  materialityReason?: string;
  verificationStandard?: VerificationStandard;
  reviewPriority?: ReviewPriority;
  isTargetCompanyClaim?: boolean;
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
  evidenceRole?: EvidenceRole;
  sourceAuthority?: SourceAuthority;
  sourceDate?: string | null;
  locator?: string;
  quoteConfidence?: Confidence;
  assessorRationale?: string;
};

export type SourceQualityNote = {
  materialId: string;
  materialName: string;
  sourceType: "file" | "url" | "seed";
  authority: SourceAuthority;
  reliability: Confidence;
  limitations: string[];
};

export type ReportClaimRef = {
  claimId: string;
  text: string;
  status: ClaimStatus;
  rationale: string;
  evidenceIds: string[];
};

export type DiligenceReport = {
  reportVersion: string;
  company: string;
  generatedAt?: string | null;
  decisionSummary: string;
  investmentThesis: string;
  keyVerifiedClaims: ReportClaimRef[];
  disputedClaims: ReportClaimRef[];
  weakOrMissingClaims: ReportClaimRef[];
  evidenceAssessment: string[];
  redFlags: string[];
  diligencePlan: string[];
  sourceQualityNotes: SourceQualityNote[];
  icRecommendation: string;
  appendixClaimLedger: ReportClaimRef[];
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
  report: DiligenceReport | null;
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
