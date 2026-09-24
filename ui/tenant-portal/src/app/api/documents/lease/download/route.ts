import { NextResponse } from 'next/server';

/**
 * PDF Lease Document Generation & Streaming Endpoint
 * Returns a binary PDF buffer with exact Content-Length & Content-Disposition headers.
 */
export async function GET() {
  try {
    // Generate valid minimal PDF binary content (PDF-1.4 standard structure)
    const pdfContent = `%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 135 >>
stream
BT
/F1 24 Tf
50 700 Td
(RESIDENTIAL LEASE AGREEMENT) Tj
/F1 12 Tf
0 -30 Td
(Tenant: Jane Doe | Property: Apt 4B, 100 Main St) Tj
0 -20 Td
(Status: Fully Executed & Signed) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000244 00000 n
0000000430 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
509
%%EOF`;

    // Convert string to Uint8Array binary buffer
    const buffer = new TextEncoder().encode(pdfContent);

    return new NextResponse(buffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="Signed_Lease_Agreement.pdf"',
        'Content-Length': buffer.byteLength.toString(),
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error generating PDF lease document:', error);
    return NextResponse.json(
      { error: 'Failed to generate lease PDF' },
      { status: 500 }
    );
  }
}
