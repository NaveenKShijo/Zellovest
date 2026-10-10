import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Custom-auth middleware (replaces Asgardeo/WSO2 protectRoute).
 *
 * The session JWT lives in localStorage (client-side custom auth), so the
 * edge middleware cannot verify it here — enforcement belongs to the
 * client-side AuthGuard plus Bearer checks on the FastAPI services.
 * This middleware stays as a passthrough so static/route matching keeps
 * working without an external identity provider round-trip.
 */
export default function middleware(_req: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
