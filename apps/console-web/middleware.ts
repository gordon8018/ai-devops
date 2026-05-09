import { type NextRequest, NextResponse } from "next/server";

const PASSWORD = process.env.CONSOLE_PASSWORD;
const COOKIE_NAME = "console_auth";

export function middleware(req: NextRequest) {
  if (!PASSWORD) return NextResponse.next();

  const cookie = req.cookies.get(COOKIE_NAME)?.value;
  if (cookie === PASSWORD) return NextResponse.next();

  const { pathname } = req.nextUrl;
  if (pathname === "/login") return NextResponse.next();

  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = "/login";
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
