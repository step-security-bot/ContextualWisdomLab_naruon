import { describe, expect, it } from 'vitest';

import { toMailDisplayText, toMailBodyText } from './mail-text';

describe('toMailDisplayText', () => {
  it('handles regular text correctly', () => {
    expect(toMailDisplayText('Hello world')).toBe('Hello world');
  });

  it('handles null values returning fallback or empty string', () => {
    expect(toMailDisplayText(null)).toBe('');
    expect(toMailDisplayText(null, 'fallback')).toBe('fallback');
  });

  it('handles undefined values', () => {
    expect(toMailDisplayText(undefined)).toBe('');
    expect(toMailDisplayText(undefined, 'fallback')).toBe('fallback');
  });

  it('handles empty strings', () => {
    expect(toMailDisplayText('')).toBe('');
    expect(toMailDisplayText('', 'fallback')).toBe('fallback'); // if empty string -> fallback in the implementation `return displayText || fallback`
  });

  it('replaces multiple whitespaces (including newlines and tabs) with a single space', () => {
    expect(toMailDisplayText('Hello \n \t world')).toBe('Hello world');
  });

  it('strips normal HTML tags', () => {
    expect(toMailDisplayText('<b>Bold</b> and <a href="link">link</a>')).toBe('Bold and link');
  });

  it('strips <script> tags and their content', () => {
    expect(toMailDisplayText('Before <script>alert("xss")</script> After')).toBe('Before After');
  });

  it('handles unclosed tags correctly', () => {
    expect(toMailDisplayText('Unclosed <div tag')).toBe('Unclosed div tag'); // implementation keeps it
  });

  it('handles unclosed <script> tags without throwing errors', () => {
    expect(toMailDisplayText('Unclosed <script> var a = 1;')).toBe('Unclosed');
  });

  it('trims leading and trailing spaces', () => {
      expect(toMailDisplayText('  Text  ')).toBe('Text');
  });
});

describe('toMailBodyText', () => {
  it('handles regular text correctly', () => {
    expect(toMailBodyText('Hello world')).toBe('Hello world');
  });

  it('handles null values', () => {
    expect(toMailBodyText(null)).toBe('');
    expect(toMailBodyText(null, 'fallback')).toBe('fallback');
  });

  it('handles undefined values', () => {
    expect(toMailBodyText(undefined)).toBe('');
    expect(toMailBodyText(undefined, 'fallback')).toBe('fallback');
  });

  it('handles empty strings', () => {
    expect(toMailBodyText('')).toBe('');
    expect(toMailBodyText('', 'fallback')).toBe('fallback');
  });

  it('strips normal HTML tags', () => {
    expect(toMailBodyText('<b>Bold</b> and <a href="link">link</a>')).toBe('Bold and link');
  });

  it('strips <script> tags and their content', () => {
    expect(toMailBodyText('Before <script>alert("xss")</script> After')).toBe('Before After');
  });

  it('collapses horizontal whitespace (spaces, tabs) to a single space', () => {
    expect(toMailBodyText('Hello \t  world')).toBe('Hello world');
  });

  it('collapses 3 or more consecutive newlines down to 2 newlines (preserves paragraphs)', () => {
    expect(toMailBodyText('Line 1\n\n\n\nLine 2')).toBe('Line 1\n\nLine 2');
  });

  it('collapses CRLF newlines down to preserved paragraph breaks', () => {
    expect(toMailBodyText('Line 1\r\n\r\n\r\nLine 2')).toBe('Line 1\n\nLine 2');
  });

  it('collapses whitespace-only blank lines down to preserved paragraph breaks', () => {
    expect(toMailBodyText('Line 1\n \n \nLine 2')).toBe('Line 1\n\nLine 2');
  });

  it('collapses mixed CRLF, tabs, and spaces down to preserved paragraph breaks', () => {
    expect(toMailBodyText('Line 1\r\n  \t  \r\n \r\nLine 2')).toBe('Line 1\n\nLine 2');
  });

  it('preserves single and double newlines', () => {
    expect(toMailBodyText('Line 1\nLine 2\n\nLine 3')).toBe('Line 1\nLine 2\n\nLine 3');
  });

  it('trims leading and trailing spaces', () => {
      expect(toMailBodyText('  Text  ')).toBe('Text');
  });
});
