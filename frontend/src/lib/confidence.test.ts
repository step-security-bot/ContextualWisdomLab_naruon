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
});
