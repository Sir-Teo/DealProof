import { NextResponse } from "next/server";
import { answerFromFixtures } from "@/lib/chat";
import { answerWithDeepSeek } from "@/lib/deepseek";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as { question?: string } | null;
  const question = body?.question?.trim();

  if (!question) {
    return NextResponse.json({ error: "Question is required." }, { status: 400 });
  }

  const deepseekAnswer = await answerWithDeepSeek(question);
  return NextResponse.json(deepseekAnswer ?? answerFromFixtures(question));
}
