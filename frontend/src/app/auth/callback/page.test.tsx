/* @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { toSafeReturnTo } from './page';

describe('auth callback return target validation', () => {
  it('allows local callback return paths', () => {
    expect(toSafeReturnTo('/settings?tab=security#oidc')).toBe('/settings?tab=security#oidc');
    expect(toSafeReturnTo('/path')).toBe('/path');
  });

  it('rejects external callback return targets and evasions', () => {
    expect(toSafeReturnTo('https://evil.example/phish')).toBe('/');
    expect(toSafeReturnTo('//evil.example/phish')).toBe('/');
    expect(toSafeReturnTo('settings')).toBe('/');
    expect(toSafeReturnTo('/\\evil.example')).toBe('/');
    expect(toSafeReturnTo(null)).toBe('/');
    expect(toSafeReturnTo('javascript:alert(1)')).toBe('/');
    expect(toSafeReturnTo('\\\\evil.com')).toBe('/');
    expect(toSafeReturnTo(' /\t/evil.com')).toBe('/');
    expect(toSafeReturnTo('http://localhost/path')).toBe('/');
  });
});
