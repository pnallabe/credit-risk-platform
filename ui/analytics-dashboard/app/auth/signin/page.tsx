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
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border p-8">
        <div className="text-center mb-8">
          <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center text-white font-bold text-lg mx-auto mb-4">
            LS
          </div>
          <h1 className="text-2xl font-bold text-gray-900">LendSmart Analytics</h1>
          <p className="text-gray-500 text-sm mt-1">Sign in to your account</p>
          {searchParams.error && (
            <p className="text-red-500 text-xs mt-2 bg-red-50 p-2 rounded-lg">
              Authentication failed. Please check your credentials.
            </p>
          )}
        </div>

        {/* Server-side action form */}
        <form action={handleSignIn} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              name="email"
              required
              placeholder="you@lendsmart.example"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              name="password"
              required
              placeholder="demo1234"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 rounded-xl transition-colors"
          >
            Sign In →
          </button>
        </form>

        <div className="mt-6 p-4 bg-blue-50 rounded-xl text-xs text-blue-700">
          <p className="font-semibold mb-1">Demo Accounts</p>
          <p>underwriter@lendsmart.example / demo1234</p>
          <p>analyst@lendsmart.example / demo1234</p>
          <p>compliance@lendsmart.example / demo1234</p>
          <p>scientist@lendsmart.example / demo1234</p>
          <p>exec@lendsmart.example / demo1234</p>
        </div>
      </div>
    </div>
  );
}
