import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import type { Session, User } from "next-auth";
import type { JWT } from "next-auth/jwt";

export type UserRole =
  | "underwriter"
  | "risk_analyst"
  | "compliance"
  | "data_scientist"
  | "executive"
  | "regulator";

// Declare module extensions for TypeScript to accept tenant fields on User and Session
declare module "next-auth" {
  interface User {
    role?: UserRole;
    tenantId?: string;
    tenantName?: string;
  }
  interface Session {
    user: User;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role?: UserRole;
    tenantId?: string;
    tenantName?: string;
  }
}

interface DemoUser {
  password: string;
  role: UserRole;
  name: string;
  tenantId: string;
  tenantName: string;
}

// Demo users categorized by Tenant for development/testing
const DEMO_USERS: Record<string, DemoUser> = {
  // --- Prosper Tenant ---
  "underwriter@prosper.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "underwriter",
    name: "Alex Chen",
    tenantId: "prosper",
    tenantName: "Prosper",
  },
  "analyst@prosper.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "risk_analyst",
    name: "Sam Rivera",
    tenantId: "prosper",
    tenantName: "Prosper",
  },
  "compliance@prosper.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "compliance",
    name: "Morgan Lee",
    tenantId: "prosper",
    tenantName: "Prosper",
  },
  "scientist@prosper.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "data_scientist",
    name: "Jordan Kim",
    tenantId: "prosper",
    tenantName: "Prosper",
  },
  "exec@prosper.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "executive",
    name: "Casey Park",
    tenantId: "prosper",
    tenantName: "Prosper",
  },

  // --- Lending Club Tenant ---
  "underwriter@lendingclub.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "underwriter",
    name: "Sarah Jenkins",
    tenantId: "lending_club",
    tenantName: "Lending Club",
  },
  "analyst@lendingclub.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "risk_analyst",
    name: "Marcus Brody",
    tenantId: "lending_club",
    tenantName: "Lending Club",
  },
  "exec@lendingclub.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "executive",
    name: "Elena Rostova",
    tenantId: "lending_club",
    tenantName: "Lending Club",
  },

  // --- Freddie Mac Tenant ---
  "analyst@freddiemac.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "risk_analyst",
    name: "David Smith",
    tenantId: "freddie_mac",
    tenantName: "Freddie Mac",
  },

  // --- Synthetic Tenant ---
  "scientist@synthetic.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "data_scientist",
    name: "AI Simulator",
    tenantId: "synthetic_tenant",
    tenantName: "Synthetic Simulator",
  },

  // --- Regulator (Platform Supervisor Scope) ---
  "regulator@platform.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "regulator",
    name: "Taylor Reyes",
    tenantId: "all",
    tenantName: "Helix Platform",
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    Credentials({
      name: "Email & Password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials): Promise<User | null> {
        const { email, password } = credentials as { email: string; password: string };
        const user = DEMO_USERS[email?.toLowerCase()];
        if (!user || user.password !== password) return null;
        return {
          id: email,
          email,
          name: user.name,
          role: user.role,
          tenantId: user.tenantId,
          tenantName: user.tenantName,
        };
      },
    }),
  ],
  session: { strategy: "jwt" },
  useSecureCookies: process.env.NODE_ENV === "production",
  cookies: {
    sessionToken: {
      name: "__session",
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role = user.role;
        token.tenantId = user.tenantId;
        token.tenantName = user.tenantName;
      }
      return token;
    },
    async session({ session, token }): Promise<Session> {
      return {
        ...session,
        user: {
          ...session.user,
          role: token.role,
          tenantId: token.tenantId,
          tenantName: token.tenantName,
        },
      };
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
});
