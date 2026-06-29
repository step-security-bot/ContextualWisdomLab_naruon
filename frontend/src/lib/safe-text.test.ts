import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import { toSafeReactText } from './safe-text';

describe('toSafeReactText', () => {
  it('keeps readable email text unmodified', () => {
    expect(toSafeReactText('AT&T: 2 < 3 and Tom "T"')).toBe('AT&T: 2 < 3 and Tom "T"');
  });

  it('keeps unsafe HTML-like text unmodified (rendering safely is React\'s job)', () => {
    const unsafeText = `<img src=x onerror="alert('xss')">`;
    expect(toSafeReactText(unsafeText)).toBe(unsafeText);
  });

  it('replaces ambiguous control characters before display', () => {
    expect(toSafeReactText('hello\u0000world')).toBe('hello\uFFFDworld');
    expect(toSafeReactText('test\u0008test')).toBe('test\uFFFDtest'); // Backspace
    expect(toSafeReactText('test\u000Btest')).toBe('test\uFFFDtest'); // Vertical Tab
    expect(toSafeReactText('test\u000Ctest')).toBe('test\uFFFDtest'); // Form Feed
    expect(toSafeReactText('test\u001Btest')).toBe('test\uFFFDtest'); // Escape
    expect(toSafeReactText('test\u007Ftest')).toBe('test\uFFFDtest'); // Delete
  });

  it('handles null values', () => {
    expect(toSafeReactText(null)).toBe('');
  });

  it('handles undefined values', () => {
    expect(toSafeReactText(undefined)).toBe('');
  });

  it('handles empty string', () => {
    expect(toSafeReactText('')).toBe('');
  });

  it('uses custom fallback for null', () => {
    expect(toSafeReactText(null, 'fallback')).toBe('fallback');
  });

  it('uses custom fallback for undefined', () => {
    expect(toSafeReactText(undefined, 'fallback')).toBe('fallback');
  });

  it('does not use fallback for empty string', () => {
    expect(toSafeReactText('', 'fallback')).toBe('');
  });

  it('removes display-ambiguous control characters for arbitrary text', () => {
    fc.assert(
      fc.property(fc.string(), (value) => {
        const safeText = toSafeReactText(value);

        expect(safeText).not.toMatch(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/);
      }),
    );
  });
});
