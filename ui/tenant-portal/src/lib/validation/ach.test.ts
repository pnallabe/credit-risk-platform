import { describe, it, expect } from 'vitest';
import { validateABARouting } from './ach';

describe('validateABARouting', () => {
  it('returns true for valid 9-digit ABA routing numbers', () => {
    // Known valid routing numbers:
    // Chase Bank: 021000021
    // Bank of America: 121000358
    // Wells Fargo: 121000248
    expect(validateABARouting('021000021')).toBe(true);
    expect(validateABARouting('121000358')).toBe(true);
    expect(validateABARouting('121000248')).toBe(true);
  });

  it('returns false for invalid 9-digit routing numbers failing ABA checksum', () => {
    expect(validateABARouting('123456789')).toBe(false);
    expect(validateABARouting('999999999')).toBe(false);
    expect(validateABARouting('111111111')).toBe(false);
  });

  it('returns false for routing numbers that do not have 9 digits', () => {
    expect(validateABARouting('02100002')).toBe(false);
    expect(validateABARouting('0210000210')).toBe(false);
    expect(validateABARouting('')).toBe(false);
  });

  it('strips non-digit formatting characters correctly', () => {
    expect(validateABARouting('021-000-021')).toBe(true);
  });
});
