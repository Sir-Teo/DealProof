export type ClaimStatus = "supported" | "weak" | "contradicted" | "missing";

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
    | "financials";
  sourceMaterial: string;
  sourceSnippet: string;
  importance: "high" | "medium" | "low";
  status: ClaimStatus;
  riskRationale: string;
};

export type EvidenceItem = {
  id: string;
  claimId: string;
  title: string;
  sourceType: "uploaded" | "supplied_url" | "derived";
  citation: string;
  snippet: string;
  stance: "supports" | "partially_supports" | "contradicts" | "not_found";
  reliability: "high" | "medium" | "low";
};

export type RiskMemo = {
  company: string;
  overallGrade: "green" | "yellow" | "red";
  investmentQuestion: string;
  keyStrengths: string[];
  materialRisks: string[];
  followUpQuestions: string[];
  icRecommendation: string;
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
  memo: RiskMemo | null;
  generatedAt: string | null;
};

export type ChatAnswer = {
  answer: string;
  citations: string[];
  confidence: "high" | "medium" | "low";
};
