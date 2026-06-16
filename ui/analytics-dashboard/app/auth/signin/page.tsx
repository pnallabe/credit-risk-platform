import { auth, signIn } from "@/auth";
import { redirect } from "next/navigation";
import { AuthError } from "next-auth";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: { callbackUrl?: string; error?: string };
}) {
  const session = await auth();
  if (session?.user) {
    redirect(searchParams.callbackUrl ?? "/");
  }

  const handleSignIn = async (formData: FormData) => {
    "use server";
    try {
      await signIn("credentials", {
        email: formData.get("email"),
        password: formData.get("password"),
        redirectTo: searchParams.callbackUrl ?? "/",
      });
    } catch (error) {
      if (error instanceof AuthError) {
        return redirect(`/auth/signin?error=${error.type}`);
      }
      throw error;
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#090d16] via-[#0f172a] to-[#1e1b4b] flex items-center justify-center px-4 relative overflow-hidden">
      {/* Decorative background glow circles */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl pointer-events-none"></div>

      <div className="w-full max-w-md bg-white/5 backdrop-blur-2xl rounded-3xl border border-white/10 p-10 relative z-10 shadow-2xl shadow-indigo-950/20">
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-gradient-to-tr from-indigo-500 to-blue-600 rounded-2xl flex items-center justify-center text-white font-black text-xl mx-auto mb-5 shadow-lg shadow-indigo-500/30 tracking-wider">
            LS
          </div>
          <h1 className="text-3xl font-black tracking-tight text-white">
            <span className="bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">
              Helix Decisions
            </span>
          </h1>
          <p className="text-indigo-200/50 text-sm mt-2 font-medium">
            AI-Driven Credit Governance Portal
          </p>
          {searchParams.error && (
            <div className="text-red-400 text-xs mt-4 bg-red-500/10 border border-red-500/20 p-3 rounded-xl flex items-center justify-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
              Authentication failed. Please verify credentials.
            </div>
          )}
        </div>

        {/* Server-side action form */}
        <form action={handleSignIn} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-indigo-300 mb-2">
              Email Address
            </label>
            <input
              type="email"
              name="email"
              required
              placeholder="you@helixdecisions.example"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-indigo-300/30 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-indigo-300 mb-2">
              Password
            </label>
            <input
              type="password"
              name="password"
              required
              placeholder="••••••••"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-indigo-300/30 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
            />
          </div>
          <button
            type="submit"
            className="w-full bg-gradient-to-r from-indigo-500 to-blue-600 hover:from-indigo-600 hover:to-blue-700 text-white font-bold py-3.5 rounded-xl transition-all duration-300 shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30 hover:scale-[1.01]"
          >
            Sign In to Dashboard
          </button>
        </form>

        <div className="mt-8 p-5 bg-indigo-500/5 border border-indigo-500/10 rounded-2xl text-xs text-indigo-200/70 space-y-2">
          <p className="font-bold text-indigo-300 uppercase tracking-wider mb-2">
            Demo Authority Roles
          </p>
          <div className="grid grid-cols-2 gap-2 font-mono">
            <div>
              <p className="text-white font-medium">Underwriter</p>
              <p className="text-[10px] text-indigo-300/50">underwriter@helixdecisions.example</p>
            </div>
            <div>
              <p className="text-white font-medium">Risk Analyst</p>
              <p className="text-[10px] text-indigo-300/50">analyst@helixdecisions.example</p>
            </div>
            <div>
              <p className="text-white font-medium">Compliance Officer</p>
              <p className="text-[10px] text-indigo-300/50">compliance@helixdecisions.example</p>
            </div>
            <div>
              <p className="text-white font-medium">Data Scientist</p>
              <p className="text-[10px] text-indigo-300/50">scientist@helixdecisions.example</p>
            </div>
          </div>
          <p className="text-[10px] text-indigo-400 font-semibold pt-1 border-t border-indigo-500/10">
            Password for all demo roles: <span className="text-white">demo1234</span>
          </p>
        </div>
      </div>
    </div>
  );
}
