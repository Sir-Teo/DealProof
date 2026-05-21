import { NextResponse } from "next/server";
import { demoAnalysis } from "@/lib/demo-data";

export async function GET() {
  return NextResponse.json(demoAnalysis);
}

export async function POST() {
  return NextResponse.json({
    ...demoAnalysis,
    generatedAt: new Date().toISOString()
  });
}
