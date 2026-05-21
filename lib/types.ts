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
  sourceType: "uploaded" | "public_web" | "derived";
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
  name: string;
  kind: "deck" | "transcript" | "financials" | "url";
  pages?: number;
  summary: string;
  excerpt: string;
};

export type DealAnalysis = {
  company: string;
  tagline: string;
  stage: string;
  materials: SourceMaterial[];
  claims: DealClaim[];
  evidence: EvidenceItem[];
  memo: RiskMemo;
  generatedAt: string;
};

export type ChatAnswer = {
  answer: string;
  citations: string[];
  confidence: "high" | "medium" | "low";
};
