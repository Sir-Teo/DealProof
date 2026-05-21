import { demoAnalysis } from "@/lib/demo-data";
import { evidenceForClaim, findRelevantClaims } from "@/lib/scoring";
import type { ChatAnswer } from "@/lib/types";

export async function answerWithDeepSeek(question: string): Promise<ChatAnswer | null> {
  const apiKey = process.env.DEEPSEEK_API_KEY;
  if (!apiKey) return null;

  const relevantClaims = findRelevantClaims(question, demoAnalysis.claims);
  const context = relevantClaims
    .map((claim) => {
      const evidence = evidenceForClaim(claim.id, demoAnalysis.evidence)
        .map((item) => `- ${item.title} [${item.citation}]: ${item.snippet}`)
        .join("\n");
      return `Claim: ${claim.text}\nStatus: ${claim.status}\nRationale: ${claim.riskRationale}\nEvidence:\n${evidence}`;
    })
    .join("\n\n");

  const response = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: "deepseek-chat",
      temperature: 0.2,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content:
            "You are DealProof, a VC diligence red-team analyst. Answer only from the provided claim/evidence context. If evidence is insufficient, say so directly, then explain what is known, what is unproven, and the next diligence ask. Keep the answer 3-5 concise sentences. Return JSON with answer, citations array, and confidence high|medium|low."
        },
        {
          role: "user",
          content: `Question: ${question}\n\nContext:\n${context}`
        }
      ]
    })
  });

  if (!response.ok) return null;
  const payload = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = payload.choices?.[0]?.message?.content;
  if (!content) return null;

  try {
    const parsed = JSON.parse(content) as ChatAnswer;
    if (parsed.answer && Array.isArray(parsed.citations) && parsed.confidence) {
      return parsed;
    }
  } catch {
    return null;
  }

  return null;
}
