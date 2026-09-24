/**
 * ABA Routing Number Validation using standard Modulo 10 algorithm:
 * (3*(d1 + d4 + d7) + 7*(d2 + d5 + d8) + 1*(d3 + d6 + d9)) % 10 === 0
 */
export function validateABARouting(routingNumber: string): boolean {
  // Strip non-digit characters
  const cleanRouting = routingNumber.replace(/\D/g, '');

  // Must be exactly 9 digits
  if (cleanRouting.length !== 9) {
    return false;
  }

  const d = cleanRouting.split('').map((char) => parseInt(char, 10));

  const weightedSum =
    3 * (d[0] + d[3] + d[6]) +
    7 * (d[1] + d[4] + d[7]) +
    1 * (d[2] + d[5] + d[8]);

  return weightedSum % 10 === 0;
}
