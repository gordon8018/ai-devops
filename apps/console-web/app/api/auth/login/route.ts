import { type NextRequest, NextResponse } from "next/server";
import { SESSION_TOKEN } from "../../../../middleware";

const PASSWORD = process.env.CONSOLE_PASSWORD;
const COOKIE_NAME = "console_auth";

export async function POST(req: NextRequest) {
  if (!PASSWORD) {
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }

  const raw: unknown = await req.json().catch(() => ({}));
  const submitted =
    raw !== null && typeof raw === "object" && "password" in raw
      ? String((raw as Record<string, unknown>).password)
      : undefined;

  if (submitted !== PASSWORD) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  const res = NextResponse.json({ success: true });
  res.cookies.set(COOKIE_NAME, SESSION_TOKEN, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}
