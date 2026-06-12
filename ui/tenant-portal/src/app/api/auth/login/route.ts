import { NextResponse } from 'next/server';
import jwt from 'jsonwebtoken';
import { canonicalizeTenantSlug } from '@/lib/tenant-routing';

// Hardcoded for MVP. In production, this would be a DB lookup.
const TENANT_MAPPING: Record<string, string> = {
  'admin@prosper.com': 'prosper',
  'admin@lendingclub.com': 'lending_club',
  'admin@freddiemac.com': 'freddie_mac',
  'admin@synthetic.com': 'synthetic_tenant',
  // Default fallback for any other agenthivehq email
  'default': 'synthetic_tenant',
};

// Must match the backend's default or env variable
const JWT_SECRET = process.env.JWT_SECRET || "dev-secret-change-me-in-production";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { email, provider, password, code } = body;

    if (!email) {
      return NextResponse.json({ error: 'Email is required' }, { status: 400 });
    }

    // MVP Mock Verification:
    // If provider is 'google', we assume the frontend Google SDK already verified them.
    // If provider is 'otp', we just mock verification (accept any non-empty code/password).
    if (provider === 'otp' && !password && !code) {
      return NextResponse.json({ error: 'OTP or Password is required' }, { status: 400 });
    }

    // Determine tenant_id based on email
    let tenantId = TENANT_MAPPING[email];
    if (!tenantId && email.endsWith('@agenthivehq.com')) {
      tenantId = TENANT_MAPPING['default'];
    } else if (!tenantId) {
      // Fallback for demo purposes
      tenantId = 'synthetic_tenant';
    }

    const tenantSlug = canonicalizeTenantSlug(tenantId);

    // Generate valid JWT signed with the same secret the Python backend uses
    const token = jwt.sign(
      {
        sub: email,
        tenant_id: tenantId,
        tenant_slug: tenantSlug,
        tenants: [tenantSlug],
        role: 'admin',
        auth_type: provider,
      },
      JWT_SECRET,
      {
        algorithm: 'HS256',
        expiresIn: '8h',
        issuer: 'risk-platform' // matches ingestion-api auth.py if needed
      }
    );

    // Return the token so the frontend can store it and use it as a Bearer token
    const useSecureCookie = process.env.NODE_ENV === 'production';
    const allowCrossSiteCookie = process.env.CROSS_SITE_COOKIE === 'true';
    const response = NextResponse.json({
      success: true,
      token,
      user: {
        email,
        tenant_id: tenantId,
        tenant_slug: tenantSlug,
      }
    });

    response.cookies.set({
      name: 'helix_tenant_token',
      value: token,
      httpOnly: true,
      secure: useSecureCookie,
      sameSite: allowCrossSiteCookie ? 'none' : 'lax',
      path: '/',
      maxAge: 60 * 60 * 8,
    });

    response.cookies.set({
      name: 'helix_tenant_slug',
      value: tenantSlug,
      httpOnly: false,
      secure: useSecureCookie,
      sameSite: allowCrossSiteCookie ? 'none' : 'lax',
      path: '/',
      maxAge: 60 * 60 * 8,
    });

    return response;
  } catch (error) {
    console.error('Login error:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
