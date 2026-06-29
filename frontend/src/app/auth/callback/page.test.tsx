/* @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { toSafeReturnTo } from './page';

describe('auth callback return target validation', () => {
  it('allows local callback return paths', () => {
    expect(toSafeReturnTo('/settings?tab=security#oidc')).toBe('/settings?tab=security#oidc');
  });

  it('rejects external callback return targets', () => {
    expect(toSafeReturnTo('https://evil.example/phish')).toBe('/');
    expect(toSafeReturnTo('//evil.example/phish')).toBe('/');
    expect(toSafeReturnTo('settings')).toBe('/');
    expect(toSafeReturnTo('/\\evil.example')).toBe('/');
    expect(toSafeReturnTo(null)).toBe('/');
  });
});
