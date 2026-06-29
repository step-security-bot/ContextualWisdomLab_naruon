## 2024-05-24 - Add `aria-busy` to async operation buttons
**Learning:** Action buttons triggering asynchronous network operations need an `aria-busy` attribute, alongside `disabled` state and visual indicators, to correctly communicate their loading state to screen reader users.
**Action:** Add `aria-busy={isLoading}` to action buttons alongside existing spinner and disabled states for network interactions.
## 2024-05-24 - Refresh button loading states
**Learning:** Adding explicit visual indicators (like `animate-spin`) and `aria-busy` to buttons alongside `disabled` states prevents multiple clicks and effectively communicates asynchronous loading to screen readers.
**Action:** When creating action buttons for async operations like '새로고침' (Refresh), always include `disabled={loading}`, `aria-busy={loading}`, adjust opacity (`disabled:opacity-60`), change cursor (`disabled:cursor-not-allowed`), spin icons, and update text to '새로고침 중'.
## 2024-05-17 - Update UI Terminology Mapping
**Learning:** Blind, global string replacement (regex) for translating or standardizing Korean UI terms can lead to semantical breaks. For example, blindly replacing "할 일" to "실행 항목" breaks other valid Korean words containing "할 일" such as "표시할 일정" (changing it to "표시실행 항목정"). Similarly, replacing "검색" with "맥락 검색" indiscriminately can lead to redundant strings like "맥락 맥락 검색".
**Action:** When updating localization strings or terminology across a large codebase, apply context-aware parsing or careful target-word bound replacements rather than naive global string matching. Always manually verify the `git diff` for readability and semantical correctness after applying bulk string manipulations.
## 2026-06-20 - Use semantic `type="search"` with custom clear buttons
**Learning:** Using `type="search"` on input fields improves mobile UX by rendering a semantic search keyboard (with a "Search" submit button instead of "Go/Enter"). However, when adding a custom clear button ('X') using UI components or Tailwind CSS, the native webkit clear button overlaps with it.
**Action:** When implementing search fields, always use `type="search"` instead of `type="text"` to get the semantic keyboard benefits. To prevent visual overlaps with custom clear icons, add the `[&::-webkit-search-cancel-button]:hidden` Tailwind utility class to hide the native webkit clear button.
## 2024-05-24 - Ensure aria-busy accompanies disabled for async UI buttons
**Learning:** Action buttons triggering asynchronous network operations that already implement `disabled={loading}` and visual spinners MUST also include an `aria-busy={loading}` attribute to correctly communicate the active loading state to screen reader users without requiring focus shifts.
**Action:** When adding or auditing buttons for async operations like '동기화 중', '전송 중', or '검색 중', ensure `aria-busy={loadingVariable}` is explicitly added alongside existing spinner and disabled states.
## 2024-05-24 - Ensure keyboard focus visibility on custom action buttons
**Learning:** Using raw `<button>` elements instead of standard UI `<Button>` components often leads to missing `focus-visible` styling, violating keyboard accessibility expectations. Custom buttons like action tags or inline controls can become invisible to keyboard users without explicit outline rules.
**Action:** When inspecting or adding non-standard `<button>` elements, always verify and add Tailwind's `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40` utilities to ensure consistent, accessible focus indicators matching the design system.
