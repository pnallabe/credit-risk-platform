import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import type { Session, User } from "next-auth";
import type { JWT } from "next-auth/jwt";

export type UserRole =
  | "underwriter"
  | "risk_analyst"
  | "compliance"
  | "data_scientist"
  | "executive";

// Demo users for development (replace with DB lookup in production)
// pragma: allowlist secret
const DEMO_USERS: Record<string, { password: string; role: UserRole; name: string }> = {
  "underwriter@lendsmart.example": { password: "demo1234", role: "underwriter", name: "Alex Chen" }, // pragma: allowlist secret
  "analyst@lendsmart.example": { password: "demo1234", role: "risk_analyst", name: "Sam Rivera" }, // pragma: allowlist secret
  "compliance@lendsmart.example": { password: "demo1234", role: "compliance", name: "Morgan Lee" }, // pragma: allowlist secret
  "scientist@lendsmart.example": { password: "demo1234", role: "data_scientist", name: "Jordan Kim" }, // pragma: allowlist secret
  "exec@lendsmart.example": { password: "demo1234", role: "executive", name: "Casey Park" }, // pragma: allowlist secret
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      name: "Email & Password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials): Promise<(User & { role: UserRole }) | null> {
        const { email, password } = credentials as { email: string; password: string };
        const user = DEMO_USERS[email?.toLowerCase()];
        if (!user || user.password !== password) return null;
        return { id: email, email, name: user.name, role: user.role };
      },
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role = (user as User & { role: UserRole }).role;
      }
      return token as JWT & { role: UserRole };
    },
    async session({ session, token }): Promise<Session & { user: { role: UserRole } }> {
      return {
        ...session,
        user: {
          ...session.user,
          role: (token as JWT & { role: UserRole }).role,
        },
      };
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
});
