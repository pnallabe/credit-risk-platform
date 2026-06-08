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
  // --- LendSmart Tenant ---
  "underwriter@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "underwriter",
    name: "Alex Chen",
    tenantId: "lendsmart",
    tenantName: "LendSmart",
  },
  "analyst@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "risk_analyst",
    name: "Sam Rivera",
    tenantId: "lendsmart",
    tenantName: "LendSmart",
  },
  "compliance@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "compliance",
    name: "Morgan Lee",
    tenantId: "lendsmart",
    tenantName: "LendSmart",
  },
  "scientist@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "data_scientist",
    name: "Jordan Kim",
    tenantId: "lendsmart",
    tenantName: "LendSmart",
  },
  "exec@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "executive",
    name: "Casey Park",
    tenantId: "lendsmart",
    tenantName: "LendSmart",
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

  // --- Regulator (Platform Supervisor Scope) ---
  "regulator@lendsmart.example": {
    password: "demo1234", // pragma: allowlist secret
    role: "regulator",
    name: "Taylor Reyes",
    tenantId: "all",
    tenantName: "AgentHive Platform",
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
