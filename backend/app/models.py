from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
]
Importance = Literal["high", "medium", "low"]


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


class DealClaim(BaseModel):
    id: str
    text: str
    category: ClaimCategory
    sourceMaterial: str
    sourceSnippet: str
    importance: Importance
    status: ClaimStatus = "missing"
    riskRationale: str = ""


class EvidenceItem(BaseModel):
    id: str
    claimId: str
    title: str
    sourceType: Literal["uploaded", "supplied_url", "derived"]
    citation: str
    snippet: str
    stance: Literal["supports", "partially_supports", "contradicts", "not_found"]
    reliability: Literal["high", "medium", "low"]


class RiskMemo(BaseModel):
    company: str
    overallGrade: Literal["green", "yellow", "red"]
    investmentQuestion: str
    keyStrengths: list[str]
    materialRisks: list[str]
    followUpQuestions: list[str]
    icRecommendation: str


class DealAnalysis(BaseModel):
    id: str
    company: str
    tagline: str = "AI diligence target"
    stage: str = "Active diligence"
    status: Literal["draft", "materials_loaded", "running", "completed", "failed"]
    error: str | None = None
    generatedAt: str | None = None
    materials: list[SourceMaterial] = Field(default_factory=list)
    claims: list[DealClaim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    memo: RiskMemo | None = None


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
