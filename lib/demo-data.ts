import type { DealAnalysis } from "@/lib/types";

export const demoAnalysis: DealAnalysis = {
  company: "CaviClear AI",
  tagline: "AI billing automation for dental clinics",
  stage: "Seed, fictional demo packet",
  generatedAt: "2026-05-21T12:00:00.000Z",
  materials: [
    {
      id: "deck",
      name: "CaviClear Seed Deck.pdf",
      kind: "deck",
      pages: 14,
      summary:
        "Founder deck positioning CaviClear as the fastest-growing AI billing platform for independent dental clinics.",
      excerpt:
        "Slide 4: We are the fastest-growing AI billing platform for dental clinics, growing 42% month over month. Slide 7: Clinics recover 18 hours per week and improve collections by 11%. Slide 10: No direct competitor offers automated denial appeals for dental."
    },
    {
      id: "transcript",
      name: "Founder Call Transcript.txt",
      kind: "transcript",
      summary:
        "Thirty-minute founder call covering customer traction, workflow, pricing, and regulatory posture.",
      excerpt:
        "Founder: We have 37 signed clinics, 24 active, and 13 onboarding. NRR is above 140%, but it is early because most customers signed in the last four months. We do not touch diagnosis, only claims and billing workflows."
    },
    {
      id: "financials",
      name: "April Financial Snapshot.csv",
      kind: "financials",
      summary:
        "Monthly ARR, churn, implementation backlog, and gross margin snapshot supplied by the company.",
      excerpt:
        "ARR: Jan $82k, Feb $118k, Mar $167k, Apr $235k. Gross margin 71%. Logo churn: one pilot clinic. Average contract value: $9.4k ARR."
    },
    {
      id: "website",
      name: "caviclear.example",
      kind: "url",
      summary:
        "Public marketing site copy supplied as a captured URL artifact for the demo.",
      excerpt:
        "CaviClear automates eligibility checks, claim scrubbing, payment posting, and denial appeal drafting for dental practices. Human review remains required before payer submission."
    }
  ],
  claims: [
    {
      id: "claim-01",
      text: "CaviClear is the fastest-growing AI billing platform for dental clinics.",
      category: "growth",
      sourceMaterial: "CaviClear Seed Deck.pdf, slide 4",
      sourceSnippet:
        "We are the fastest-growing AI billing platform for dental clinics, growing 42% month over month.",
      importance: "high",
      status: "weak",
      riskRationale:
        "Revenue growth is strong in the uploaded financials, but the superlative fastest-growing is unsupported by market-wide benchmarks."
    },
    {
      id: "claim-02",
      text: "Monthly ARR grew from $82k to $235k over four months.",
      category: "financials",
      sourceMaterial: "April Financial Snapshot.csv",
      sourceSnippet: "ARR: Jan $82k, Feb $118k, Mar $167k, Apr $235k.",
      importance: "high",
      status: "supported",
      riskRationale:
        "The claim ties directly to the uploaded financial snapshot and can be reconciled from the listed monthly ARR values."
    },
    {
      id: "claim-03",
      text: "Clinics recover 18 staff hours per week and improve collections by 11%.",
      category: "customer_roi",
      sourceMaterial: "CaviClear Seed Deck.pdf, slide 7",
      sourceSnippet:
        "Clinics recover 18 hours per week and improve collections by 11%.",
      importance: "high",
      status: "weak",
      riskRationale:
        "The deck states the ROI, but the packet lacks customer-level cohort data, sample size, and pre/post methodology."
    },
    {
      id: "claim-04",
      text: "There is no direct competitor offering automated denial appeals for dental.",
      category: "competition",
      sourceMaterial: "CaviClear Seed Deck.pdf, slide 10",
      sourceSnippet:
        "No direct competitor offers automated denial appeals for dental.",
      importance: "medium",
      status: "contradicted",
      riskRationale:
        "Public dental revenue-cycle vendors advertise denial management and automation-adjacent workflows, so the no direct competitor language is too broad."
    },
    {
      id: "claim-05",
      text: "CaviClear has 37 signed clinics, with 24 active and 13 onboarding.",
      category: "growth",
      sourceMaterial: "Founder Call Transcript.txt",
      sourceSnippet:
        "We have 37 signed clinics, 24 active, and 13 onboarding.",
      importance: "high",
      status: "supported",
      riskRationale:
        "The founder call and financial snapshot are directionally consistent with a small but real installed base."
    },
    {
      id: "claim-06",
      text: "Net revenue retention is above 140%.",
      category: "retention",
      sourceMaterial: "Founder Call Transcript.txt",
      sourceSnippet:
        "NRR is above 140%, but it is early because most customers signed in the last four months.",
      importance: "medium",
      status: "weak",
      riskRationale:
        "The founder caveat materially limits the claim because cohort age is too short to trust expansion behavior."
    },
    {
      id: "claim-07",
      text: "The product does not touch diagnosis and only supports billing workflows.",
      category: "compliance",
      sourceMaterial: "Founder Call Transcript.txt",
      sourceSnippet:
        "We do not touch diagnosis, only claims and billing workflows.",
      importance: "high",
      status: "supported",
      riskRationale:
        "Uploaded materials consistently describe billing support with human review before payer submission."
    },
    {
      id: "claim-08",
      text: "Human review remains required before payer submission.",
      category: "compliance",
      sourceMaterial: "caviclear.example",
      sourceSnippet:
        "Human review remains required before payer submission.",
      importance: "high",
      status: "supported",
      riskRationale:
        "The website artifact explicitly states a human-in-the-loop compliance control."
    },
    {
      id: "claim-09",
      text: "Average contract value is $9.4k ARR.",
      category: "pricing",
      sourceMaterial: "April Financial Snapshot.csv",
      sourceSnippet: "Average contract value: $9.4k ARR.",
      importance: "medium",
      status: "supported",
      riskRationale:
        "The claim is directly stated in the supplied financial snapshot."
    },
    {
      id: "claim-10",
      text: "The dental billing automation market is a $6B annual opportunity.",
      category: "market",
      sourceMaterial: "CaviClear Seed Deck.pdf, slide 5",
      sourceSnippet:
        "Dental billing automation is a $6B annual opportunity across the US.",
      importance: "high",
      status: "missing",
      riskRationale:
        "The packet provides no bottom-up clinic count, spend-per-clinic, payer workflow, or credible external market source."
    }
  ],
  evidence: [
    {
      id: "ev-01",
      claimId: "claim-01",
      title: "ARR growth reconciles to 42% average MoM",
      sourceType: "derived",
      citation: "Derived from April Financial Snapshot.csv",
      snippet:
        "$82k to $235k ARR over three monthly intervals implies roughly 42% average monthly growth.",
      stance: "partially_supports",
      reliability: "high"
    },
    {
      id: "ev-02",
      claimId: "claim-01",
      title: "No category benchmark supplied",
      sourceType: "public_web",
      citation: "Public benchmark search placeholder",
      snippet:
        "No cited public ranking or denominator supports fastest-growing relative to every AI billing platform.",
      stance: "not_found",
      reliability: "medium"
    },
    {
      id: "ev-03",
      claimId: "claim-02",
      title: "Financial snapshot ARR table",
      sourceType: "uploaded",
      citation: "April Financial Snapshot.csv",
      snippet: "ARR: Jan $82k, Feb $118k, Mar $167k, Apr $235k.",
      stance: "supports",
      reliability: "high"
    },
    {
      id: "ev-04",
      claimId: "claim-03",
      title: "Deck ROI claim lacks methodology",
      sourceType: "uploaded",
      citation: "CaviClear Seed Deck.pdf, slide 7",
      snippet:
        "The slide gives hours saved and collections uplift but does not include sample size, baseline, or customer names.",
      stance: "partially_supports",
      reliability: "medium"
    },
    {
      id: "ev-05",
      claimId: "claim-04",
      title: "Dental RCM vendors advertise denial workflows",
      sourceType: "public_web",
      citation: "Public dental RCM vendor landscape review",
      snippet:
        "Multiple dental revenue-cycle vendors describe denial management, claim scrubbing, and collections automation.",
      stance: "contradicts",
      reliability: "medium"
    },
    {
      id: "ev-06",
      claimId: "claim-05",
      title: "Founder call traction statement",
      sourceType: "uploaded",
      citation: "Founder Call Transcript.txt",
      snippet: "37 signed clinics, 24 active, and 13 onboarding.",
      stance: "supports",
      reliability: "medium"
    },
    {
      id: "ev-07",
      claimId: "claim-06",
      title: "NRR caveat from founder call",
      sourceType: "uploaded",
      citation: "Founder Call Transcript.txt",
      snippet:
        "NRR is above 140%, but it is early because most customers signed in the last four months.",
      stance: "partially_supports",
      reliability: "medium"
    },
    {
      id: "ev-08",
      claimId: "claim-07",
      title: "Scope limited to billing workflows",
      sourceType: "uploaded",
      citation: "Founder Call Transcript.txt",
      snippet: "We do not touch diagnosis, only claims and billing workflows.",
      stance: "supports",
      reliability: "medium"
    },
    {
      id: "ev-09",
      claimId: "claim-08",
      title: "Human review marketing control",
      sourceType: "uploaded",
      citation: "caviclear.example",
      snippet:
        "Human review remains required before payer submission.",
      stance: "supports",
      reliability: "medium"
    },
    {
      id: "ev-10",
      claimId: "claim-09",
      title: "ACV source row",
      sourceType: "uploaded",
      citation: "April Financial Snapshot.csv",
      snippet: "Average contract value: $9.4k ARR.",
      stance: "supports",
      reliability: "high"
    },
    {
      id: "ev-11",
      claimId: "claim-10",
      title: "Market sizing support absent",
      sourceType: "public_web",
      citation: "Market sizing source not provided",
      snippet:
        "No bottom-up calculation or third-party source in the packet validates the $6B market size.",
      stance: "not_found",
      reliability: "medium"
    }
  ],
  memo: {
    company: "CaviClear AI",
    overallGrade: "yellow",
    investmentQuestion:
      "Is CaviClear an early but real wedge into dental revenue-cycle automation, or a services-heavy billing tool with overstated category novelty?",
    keyStrengths: [
      "ARR growth from $82k to $235k in four months is internally supported by the uploaded financial snapshot.",
      "The product focuses on a painful administrative workflow with measurable time-savings potential.",
      "Compliance posture is more credible because materials consistently state billing-only scope and human review before submission."
    ],
    materialRisks: [
      "Fastest-growing and $6B market-size claims are not supported by external benchmarks or a bottom-up model.",
      "ROI claims need customer-level proof, named references, and methodology before they should influence valuation.",
      "No-competitor language is likely overstated given existing dental RCM and denial-management vendors."
    ],
    followUpQuestions: [
      "Provide the customer-level ROI workbook behind the 18 hours/week and 11% collections claims.",
      "Show a bottom-up TAM model by US dental clinics, biller spend, and realistic attach rate.",
      "List competitors by workflow coverage and explain why dental denial appeals are technically differentiated.",
      "Break out signed, active, onboarding, churned, and expansion ARR by cohort month."
    ],
    icRecommendation:
      "Proceed to partner diligence only if customer references validate ROI and the team replaces unsupported market/competition claims with evidence-backed sizing. Current grade: yellow, promising workflow with material claim-risk."
  }
};
