import { describe, it, expect } from 'vitest';
import { toConfidencePercent } from './confidence';

describe('toConfidencePercent', () => {
  it('returns undefined for non-number inputs', () => {
    expect(toConfidencePercent(undefined)).toBeUndefined();
    expect(toConfidencePercent(null as unknown as number)).toBeUndefined();
    expect(toConfidencePercent('80' as unknown as number)).toBeUndefined();
    expect(toConfidencePercent(NaN)).toBeUndefined();
    expect(toConfidencePercent(Infinity)).toBeUndefined();
    expect(toConfidencePercent(-Infinity)).toBeUndefined();
  });

  it('handles percentage values correctly (0 to 100)', () => {
    expect(toConfidencePercent(0)).toBe(0);
    expect(toConfidencePercent(50)).toBe(50);
    expect(toConfidencePercent(85.6)).toBe(86);
    expect(toConfidencePercent(100)).toBe(100);
  });

  it('converts fraction values to percentages (0 to 1)', () => {
    expect(toConfidencePercent(0.5)).toBe(50);
    expect(toConfidencePercent(0.856)).toBe(86); // Note: 0.856 * 100 = 85.6, then Math.round -> 86
    expect(toConfidencePercent(1)).toBe(100); // 1 is ambiguous (could be 1% or 100%), but the implementation favors 100% since it multiplies by 100
  });

  it('clamps values to the 0-100 range', () => {
    expect(toConfidencePercent(-10)).toBe(0);
    expect(toConfidencePercent(150)).toBe(100);
    expect(toConfidencePercent(-0.1)).toBe(0);
  });

  it('handles values just outside the 0-1 fraction range as literal percentages', () => {
    expect(toConfidencePercent(1)).toBe(100);
    // 1.01 is > 1, so it is treated as a percentage (1.01%) and rounded to 1
    expect(toConfidencePercent(1.01)).toBe(1);
    // 1.5 is > 1, so treated as 1.5% -> rounded to 2%
    expect(toConfidencePercent(1.5)).toBe(2);
    // 99.5 is > 1, treated as 99.5% -> rounded to 100%
    expect(toConfidencePercent(99.5)).toBe(100);
  });

  it('handles floating point precision gracefully', () => {
    // 0.1 + 0.2 = 0.30000000000000004
    expect(toConfidencePercent(0.1 + 0.2)).toBe(30);
    // 0.14 * 100 = 14.000000000000002
    expect(toConfidencePercent(0.14)).toBe(14);
  });

  it('handles exact rounding thresholds correctly', () => {
    // 0.854 * 100 = 85.4 -> 85
    expect(toConfidencePercent(0.854)).toBe(85);
    // 0.855 * 100 = 85.5 -> 86
    expect(toConfidencePercent(0.855)).toBe(86);
    // 85.4 -> 85
    expect(toConfidencePercent(85.4)).toBe(85);
    // 85.5 -> 86
    expect(toConfidencePercent(85.5)).toBe(86);
  });

  it('normalizes negative zero to positive zero', () => {
    const percent = toConfidencePercent(-0);

    expect(Object.is(percent, 0)).toBe(true);
    expect(Object.is(percent, -0)).toBe(false);
  });
});
