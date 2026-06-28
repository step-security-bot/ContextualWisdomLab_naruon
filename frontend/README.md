# AI Email Client Frontend

Next.js app for the threaded inbox, email detail pane, 맥락 종합, 실행 항목, reply composer, and 관계 맥락.

## Setup

```bash
npm install
npm test
npm run lint
npm run build
npm run dev
```

Open <http://localhost:3000>. Browser requests use same-origin `/api/*`; in local development the server route handler defaults to `http://127.0.0.1:8000`, while production deployments must set `BACKEND_INTERNAL_URL` at runtime.

## Threading UI contract

- Inbox rows show selected state and thread message counts.
- Search results use the same date/thread metadata shape as inbox results.
- Detail view clears stale conversation state when switching emails.
- Conversation history shows oldest-to-newest order and marks the selected message.
- Thread fetch failures are visible and retryable.
- Reply sends include `In-Reply-To` and `References` metadata.

## Local docs note

This project uses Next.js 16. The local guidance lives under `node_modules/next/dist/docs/` after `npm install`.
