import { asgardeoMiddleware, createRouteMatcher } from "@asgardeo/nextjs/middleware";

/**
 * Pages that require an authenticated Asgardeo session. Unauthenticated
 * requests are redirected to /login (see protectRoute below). Public
 * entry points (/login), the OIDC callback (/auth/callback) and backend
 * API routes (/api/*) intentionally pass through untouched.
 */
const isProtectedRoute = createRouteMatcher([
    "/",
    "/assistant(.*)",
    "/compliance(.*)",
    "/integrations(.*)",
    "/licenses(.*)",
    "/maverick-spend(.*)",
    "/renewals(.*)",
    "/settings(.*)",
    "/upload(.*)",
    "/vendors(.*)",
]);

export default asgardeoMiddleware(async (asgardeo, req) => {
    if (isProtectedRoute(req)) {
        // Return the redirect response — discarding it would let the
        // request fall through to the protected page (NextResponse.next()).
        return asgardeo.protectRoute({ redirect: "/login" });
    }
});

export const config = {
    matcher: [
        "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
        "/(api|trpc)(.*)",
    ],
};
