import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    // ── Credentials (email + OTP) ──────────────────────────────
    Credentials({
      id: "credentials",
      name: "Email OTP",
      credentials: {
        email: { label: "Email", type: "email", placeholder: "you@example.com" },
        otp: { label: "One-Time Password", type: "text", placeholder: "123456" },
      },
      async authorize(credentials) {
        // In production: verify OTP sent to email
        // For development: accept any 6-digit OTP
        const { email, otp } = credentials as { email: string; otp: string };
        if (!email || !otp) return null;

        if (process.env.NODE_ENV !== "production" && /^\d{6}$/.test(otp)) {
          return {
            id: `user-${Buffer.from(email).toString("hex").slice(0, 8)}`,
            email,
            name: email.split("@")[0],
            role: "applicant",
          };
        }
        return null;
      },
    }),

    // ── Google OAuth (feature-flagged) ─────────────────────────
    ...(process.env.GOOGLE_CLIENT_ID
      ? [
          Google({
            clientId: process.env.GOOGLE_CLIENT_ID!,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
          }),
        ]
      : []),
  ],

  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },

  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role = (user as { role?: string }).role ?? "applicant";
        token.application_ids = [];
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as { role?: string; application_ids?: string[] }).role =
          (token.role as string) ?? "applicant";
        (session.user as { application_ids?: string[] }).application_ids =
          (token.application_ids as string[]) ?? [];
      }
      return session;
    },
  },

  pages: {
    signIn: "/auth/signin",
    error: "/auth/error",
  },
});
