import { toSafeReactText } from './safe-text';

function stripHtmlLikeSegments(rawText: string) {
  const lowerText = rawText.toLowerCase();
  let displayText = '';
  let index = 0;

  while (index < rawText.length) {
    if (lowerText.startsWith('<script', index)) {
      const closeStart = lowerText.indexOf('</script', index + 7);
      if (closeStart === -1) break;
      const closeEnd = rawText.indexOf('>', closeStart + 8);
      displayText += ' ';
      index = closeEnd === -1 ? rawText.length : closeEnd + 1;
      continue;
    }

    if (rawText[index] === '<') {
      const tagEnd = rawText.indexOf('>', index + 1);
      displayText += ' ';
      index = tagEnd === -1 ? index + 1 : tagEnd + 1;
      continue;
    }

    displayText += rawText[index];
    index += 1;
  }

  return displayText.split('<').join(' ').split('>').join(' ');
}

export function toMailDisplayText(value: string | null | undefined, fallback = '') {
  const rawText = toSafeReactText(value?.trim() || null, fallback);
  const displayText = stripHtmlLikeSegments(rawText)
    .replace(/\s+/g, ' ')
    .trim();
  return displayText || fallback;
}

export function toMailBodyText(value: string | null | undefined, fallback = '') {
  const rawText = toSafeReactText(value?.trim() || null, fallback);
  const displayText = stripHtmlLikeSegments(rawText)
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n(?: *\n){2,}/g, '\n\n')
    .trim();
  return displayText || fallback;
}
