import { type NextRequest, NextResponse } from "next/server";

const PASSWORD = process.env.CONSOLE_PASSWORD;
const COOKIE_NAME = "console_auth";

export async function POST(req: NextRequest) {
  if (!PASSWORD) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 500 });
  }
  const body = await req.json().catch(() => ({}));
  if (body.password !== PASSWORD) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }
  const res = NextResponse.json({ success: true });
  res.cookies.set(COOKIE_NAME, PASSWORD, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}
