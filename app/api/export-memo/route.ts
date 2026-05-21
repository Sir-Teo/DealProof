import { NextResponse } from "next/server";
import { demoAnalysis } from "@/lib/demo-data";
import { generateMemoMarkdown } from "@/lib/scoring";

export async function GET() {
  const markdown = generateMemoMarkdown(demoAnalysis.memo);
  return new NextResponse(markdown, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": 'attachment; filename="dealproof-red-team-memo.md"'
    }
  });
}
