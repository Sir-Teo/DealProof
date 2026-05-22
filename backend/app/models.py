from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import DEFAULT_STAGE, DEFAULT_TAGLINE

ClaimStatus = Literal["supported", "weak", "contradicted", "missing"]
ClaimCategory = Literal[
    "market",
    "growth",
    "customer_roi",
    "competition",
    "pricing",
    "retention",
    "compliance",
    "financials",
    "product",
    "team",
    "go_to_market",
    "fundraising",
    "legal",
    "operations",
]
Importance = Literal["high", "medium", "low"]
Confidence = Literal["high", "medium", "low"]
DecisionImpact = Literal["high", "medium", "low"]
ReviewerStatus = Literal["unreviewed", "verified", "needs_evidence"]
SourceIndependence = Literal["founder_supplied", "internal", "third_party", "derived"]


class SourceMaterial(BaseModel):
    id: str
    deal_id: str
    name: str
    kind: Literal["deck", "transcript", "financials", "url", "document"]
    source_type: Literal["file", "url", "seed"]
    path: str | None = None
    url: str | None = None
    summary: str = ""
    excerpt: str = ""
    text: str = ""


class MaterialChunk(BaseModel):
    id: str
    material_id: str
    deal_id: str
    citation: str
    text: str
    sourceName: str = ""
    sourceUrl: str | None = None
    sourceType: Literal["file", "url", "seed"] = "file"
    chunkIndex: int = 0


class DealProfile(BaseModel):
    sector: str = "Unknown"
    businessModel: str = "Unknown"
    customer: str = "Unknown"
    stage: str = DEFAULT_STAGE
    materialMix: list[str] = Field(default_factory=list)


class DealClaim(BaseModel):
    id: str
    text: str
    category: ClaimCategory
    sourceMaterial: str
    sourceSnippet: str
    importance: Importance
    status: ClaimStatus = "missing"
    riskRationale: str = ""
    confidence: Confidence = "low"
    qualityScore: int = 0
    qualityIssues: list[str] = Field(default_factory=list)
    verificationNeed: str = ""
    decisionImpact: DecisionImpact = "medium"
    reviewerStatus: ReviewerStatus = "unreviewed"
    reviewerNotes: str = ""


class EvidenceItem(BaseModel):
    id: str
    claimId: str
    title: str
    sourceType: Literal["uploaded", "supplied_url", "derived"]
    citation: str
    snippet: str
    stance: Literal["supports", "partially_supports", "contradicts", "not_found"]
    reliability: Literal["high", "medium", "low"]
    sourceIndependence: SourceIndependence = "internal"
    relevanceScore: float = 0
    quoteSpan: str | None = None
    sourceMaterialId: str | None = None
    sourceName: str | None = None
    sourceUrl: str | None = None
    chunkIndex: int | None = None
    retrievedAt: str | None = None


class RiskMemo(BaseModel):
    company: str
    overallGrade: Literal["green", "yellow", "red"]
    investmentQuestion: str
    keyStrengths: list[str]
    materialRisks: list[str]
    followUpQuestions: list[str]
    icRecommendation: str
    executiveSummary: str = ""
    thesisAssessment: str = ""
    evidenceMap: list[str] = Field(default_factory=list)
    keyRisks: list[str] = Field(default_factory=list)
    nextDiligenceRequests: list[str] = Field(default_factory=list)
    decisionDrivers: list[str] = Field(default_factory=list)


class QualityReview(BaseModel):
    memoReadinessScore: int = 0
    globalWarnings: list[str] = Field(default_factory=list)
    duplicatedClaims: list[str] = Field(default_factory=list)
    lowValueClaims: list[str] = Field(default_factory=list)
    recommendedFollowUpEvidence: list[str] = Field(default_factory=list)
    overconfidenceWarnings: list[str] = Field(default_factory=list)


class DealAnalysis(BaseModel):
    id: str
    company: str
    tagline: str = DEFAULT_TAGLINE
    stage: str = DEFAULT_STAGE
    status: Literal["draft", "materials_loaded", "running", "completed", "failed"]
    error: str | None = None
    generatedAt: str | None = None
    materials: list[SourceMaterial] = Field(default_factory=list)
    claims: list[DealClaim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    profile: DealProfile | None = None
    memo: RiskMemo | None = None
    qualityReview: QualityReview | None = None


class DealProfileGeneration(BaseModel):
    profile: DealProfile


class ClaimExtraction(BaseModel):
    claims: list[DealClaim]


class EvidenceAssessment(BaseModel):
    claim: DealClaim
    evidence: list[EvidenceItem]


class EvidenceAssessments(BaseModel):
    assessments: list[EvidenceAssessment]


class MemoGeneration(BaseModel):
    memo: RiskMemo


class ChatAnswer(BaseModel):
    answer: str
    citations: list[str]
    confidence: Literal["high", "medium", "low"]
