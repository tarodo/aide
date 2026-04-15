# Frontend Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `aide/frontend/` Vite + React + Mantine package and ship a working login → authenticated app shell. A user opening the site is redirected to `/login`, signs in, lands on `/` inside the `AppShell`, and can sign out. Access-token refresh on 401 works transparently.

**Architecture:** Feature-based monorepo package. Vite dev server during development; static build served by nginx in production. `ky` HTTP client with `beforeRequest`/`afterResponse` hooks for bearer-token injection and single-flight 401 refresh. Auth state split — access token in React context + module-level ref (XSS-hardened), refresh token in `localStorage`. TanStack Query owns server state; `AuthContext` owns session lifecycle; React Router guards protected routes.

**Tech Stack:** React 18, TypeScript 5.5+ (strict), Mantine v7, React Router v6, TanStack Query v5, `ky`, Zod, `@mantine/form` + `mantine-form-zod-resolver`, `@tabler/icons-react`, Vitest, React Testing Library, MSW v2, pnpm 9, Node.js 20 LTS.

**Related docs:**
- Spec: [docs/superpowers/specs/2026-04-15-frontend-mantine-spa-design.md](../specs/2026-04-15-frontend-mantine-spa-design.md)
- Roadmap: [2026-04-15-frontend-roadmap.md](2026-04-15-frontend-roadmap.md)

**Prerequisites:**
- Node.js 20 LTS installed locally (`node -v` → `v20.x`).
- pnpm 9 installed (`pnpm -v` → `9.x`). Install via `corepack enable` + `corepack prepare pnpm@latest --activate` if absent.
- Backend runs at `http://localhost:8001` (via `make up`) for Task 7 (OpenAPI type generation). Backend must stay running any time `pnpm gen:types` is executed.

**File structure produced by this phase:**

```
frontend/
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── vitest.config.ts
├── index.html
├── postcss.config.cjs
├── .eslintrc.cjs
├── .eslintignore
├── .prettierrc
├── .prettierignore
├── .gitignore
├── scripts/
│   └── generate-types.sh
└── src/
    ├── main.tsx
    ├── app/
    │   ├── router.tsx
    │   ├── theme.ts
    │   ├── queryClient.ts
    │   └── layout/
    │       ├── AppShell.tsx
    │       ├── TopBar.tsx
    │       └── SideNav.tsx
    ├── api/
    │   ├── client.ts
    │   ├── types.gen.ts        # generated — never hand-edited
    │   └── endpoints/
    │       └── auth.ts
    ├── features/
    │   ├── auth/
    │   │   ├── AuthContext.tsx
    │   │   ├── useAuth.ts
    │   │   ├── RequireAuth.tsx
    │   │   ├── LoginPage.tsx
    │   │   └── tokenStorage.ts
    │   └── home/
    │       └── HomePage.tsx
    ├── shared/
    │   └── utils/
    │       └── notifications.ts
    └── tests/
        ├── setup.ts
        ├── test-utils.tsx
        └── msw/
            ├── server.ts
            └── handlers.ts
```

File responsibilities:

- `vite.config.ts` — Vite dev server + build. Proxies `/api` to backend during dev.
- `tsconfig.json` — TS app config (strict, ESM).
- `tsconfig.node.json` — TS config used by Vite/Vitest config files.
- `vitest.config.ts` — Vitest + jsdom + path aliases.
- `postcss.config.cjs` — required by Mantine v7 (postcss-preset-mantine).
- `src/main.tsx` — app bootstrap, providers chain.
- `src/app/router.tsx` — route tree.
- `src/app/theme.ts` — Mantine theme (B/W palette).
- `src/app/queryClient.ts` — single `QueryClient` instance config.
- `src/app/layout/*` — shell, header, side nav.
- `src/api/client.ts` — `ky` instance + auth hooks.
- `src/api/types.gen.ts` — OpenAPI-derived types (generated).
- `src/api/endpoints/auth.ts` — login + refresh + getMe functions.
- `src/features/auth/tokenStorage.ts` — access (memory) + refresh (localStorage) storage.
- `src/features/auth/AuthContext.tsx` — session state + actions.
- `src/features/auth/useAuth.ts` — convenience hook over context.
- `src/features/auth/RequireAuth.tsx` — protected-route wrapper.
- `src/features/auth/LoginPage.tsx` — login form.
- `src/features/home/HomePage.tsx` — authenticated landing stub.
- `src/shared/utils/notifications.ts` — toast helpers.
- `src/tests/*` — test harness + MSW handlers.

---

## Task 1: Create package scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/.gitignore`

- [ ] **Step 1: Create `frontend/` directory structure**

Run:
```bash
mkdir -p frontend/src frontend/scripts
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "@aide/frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.1"
  },
  "engines": {
    "node": ">=20",
    "pnpm": ">=9"
  }
}
```

- [ ] **Step 3: Install dependencies**

Run:
```bash
cd frontend && pnpm install
```

Expected: installs dependencies, writes `pnpm-lock.yaml`.

- [ ] **Step 4: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 5: Write `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 6: Write `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 7: Write `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AIDE Metastore</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Write `frontend/src/main.tsx` (hello world)**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div>AIDE Metastore (scaffold ok)</div>
  </React.StrictMode>,
);
```

- [ ] **Step 9: Write `frontend/.gitignore`**

```
node_modules
dist
.vite
*.log
coverage
.DS_Store
```

- [ ] **Step 10: Verify dev server boots**

Run:
```bash
cd frontend && pnpm dev
```

Expected: Vite logs `Local: http://localhost:5173/`. Open in browser — page shows `AIDE Metastore (scaffold ok)`. Stop the dev server (`Ctrl+C`).

- [ ] **Step 11: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold Vite + React + TS"
```

---

## Task 2: ESLint + Prettier

**Files:**
- Create: `frontend/.eslintrc.cjs`
- Create: `frontend/.eslintignore`
- Create: `frontend/.prettierrc`
- Create: `frontend/.prettierignore`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add lint/format dev dependencies**

Run:
```bash
cd frontend && pnpm add -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-react-refresh prettier
```

- [ ] **Step 2: Write `frontend/.eslintrc.cjs`**

```js
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 2022, sourceType: 'module' },
  settings: { react: { version: 'detect' } },
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
};
```

- [ ] **Step 3: Write `frontend/.eslintignore`**

```
node_modules
dist
coverage
src/api/types.gen.ts
```

- [ ] **Step 4: Write `frontend/.prettierrc`**

```json
{
  "singleQuote": true,
  "semi": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}
```

- [ ] **Step 5: Write `frontend/.prettierignore`**

```
node_modules
dist
coverage
pnpm-lock.yaml
src/api/types.gen.ts
```

- [ ] **Step 6: Add scripts to `frontend/package.json`**

Modify the `scripts` object to:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint \"src/**/*.{ts,tsx}\"",
    "format": "prettier --write \"src/**/*.{ts,tsx,css,json}\"",
    "typecheck": "tsc --noEmit"
  }
```

- [ ] **Step 7: Run lint and typecheck to confirm clean**

Run:
```bash
cd frontend && pnpm lint && pnpm typecheck
```

Expected: both commands exit 0.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): add eslint + prettier"
```

---

## Task 3: Mantine + theme

**Files:**
- Create: `frontend/postcss.config.cjs`
- Create: `frontend/src/app/theme.ts`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Install Mantine + required PostCSS plugins + fonts**

Run:
```bash
cd frontend && pnpm add @mantine/core @mantine/hooks @mantine/notifications @tabler/icons-react @fontsource/inter @fontsource/jetbrains-mono
cd frontend && pnpm add -D postcss postcss-preset-mantine postcss-simple-vars
```

- [ ] **Step 2: Write `frontend/postcss.config.cjs`**

Mantine v7 requires this config. Without it, Mantine styles break.

```js
module.exports = {
  plugins: {
    'postcss-preset-mantine': {},
    'postcss-simple-vars': {
      variables: {
        'mantine-breakpoint-xs': '36em',
        'mantine-breakpoint-sm': '48em',
        'mantine-breakpoint-md': '62em',
        'mantine-breakpoint-lg': '75em',
        'mantine-breakpoint-xl': '88em',
      },
    },
  },
};
```

- [ ] **Step 3: Write `frontend/src/app/theme.ts`**

```ts
import { createTheme, type MantineColorsTuple } from '@mantine/core';

const black: MantineColorsTuple = [
  '#f7f7f7',
  '#ececec',
  '#d9d9d9',
  '#b8b8b8',
  '#8a8a8a',
  '#666666',
  '#444444',
  '#2a2a2a',
  '#141414',
  '#000000',
];

const diffAdded: MantineColorsTuple = [
  '#f5fbf5',
  '#e8f3e8',
  '#c9e4c9',
  '#a6d3a6',
  '#83c283',
  '#5cb05c',
  '#3a9e3a',
  '#2d842d',
  '#226a22',
  '#0a6b3a',
];

const diffRemoved: MantineColorsTuple = [
  '#fdf5f5',
  '#fae7e7',
  '#f2caca',
  '#e9a6a6',
  '#e08383',
  '#d85c5c',
  '#d03a3a',
  '#b92d2d',
  '#9d2222',
  '#cc3333',
];

export const theme = createTheme({
  primaryColor: 'black',
  primaryShade: 9,
  colors: { black, diffAdded, diffRemoved },
  fontFamily: '"Inter", -apple-system, "Segoe UI", sans-serif',
  fontFamilyMonospace: '"JetBrains Mono", "SF Mono", monospace',
  headings: { fontFamily: 'inherit', fontWeight: '600' },
  radius: { xs: '4px', sm: '6px', md: '8px', lg: '12px', xl: '16px' },
  defaultRadius: 'sm',
  spacing: { xs: '6px', sm: '10px', md: '14px', lg: '20px', xl: '28px' },
});
```

- [ ] **Step 4: Update `frontend/src/main.tsx` to wrap with `MantineProvider`**

```tsx
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';

import { theme } from './app/theme';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <div>AIDE Metastore (Mantine ok)</div>
    </MantineProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 5: Verify dev server renders**

Run:
```bash
cd frontend && pnpm dev
```

Expected: page renders, no console errors, body uses Inter font (DevTools → Elements → Computed → `font-family: "Inter", ...`). Stop the server.

- [ ] **Step 6: Typecheck and lint**

Run:
```bash
cd frontend && pnpm lint && pnpm typecheck
```

Expected: both exit 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add mantine theme + notifications"
```

---

## Task 4: React Router

**Files:**
- Create: `frontend/src/app/router.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/features/home/HomePage.tsx` (stub)
- Create: `frontend/src/features/auth/LoginPage.tsx` (stub)

- [ ] **Step 1: Install React Router**

Run:
```bash
cd frontend && pnpm add react-router-dom
```

- [ ] **Step 2: Write placeholder `frontend/src/features/home/HomePage.tsx`**

```tsx
export function HomePage() {
  return <div>Home (placeholder)</div>;
}
```

- [ ] **Step 3: Write placeholder `frontend/src/features/auth/LoginPage.tsx`**

```tsx
export function LoginPage() {
  return <div>Login (placeholder)</div>;
}
```

- [ ] **Step 4: Write `frontend/src/app/router.tsx`**

```tsx
import { createBrowserRouter } from 'react-router-dom';

import { HomePage } from '@/features/home/HomePage';
import { LoginPage } from '@/features/auth/LoginPage';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/', element: <HomePage /> },
  { path: '*', element: <div>404</div> },
]);
```

- [ ] **Step 5: Update `frontend/src/main.tsx` to use `RouterProvider`**

```tsx
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { RouterProvider } from 'react-router-dom';

import { theme } from './app/theme';
import { router } from './app/router';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <RouterProvider router={router} />
    </MantineProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Manually verify routes**

Run:
```bash
cd frontend && pnpm dev
```

Expected: `/` renders `Home (placeholder)`; `/login` renders `Login (placeholder)`; `/nonexistent` renders `404`. Stop the server.

- [ ] **Step 7: Typecheck and lint**

Run:
```bash
cd frontend && pnpm lint && pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add router stub routes"
```

---

## Task 5: TanStack Query

**Files:**
- Create: `frontend/src/app/queryClient.ts`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Install TanStack Query + devtools**

Run:
```bash
cd frontend && pnpm add @tanstack/react-query
cd frontend && pnpm add -D @tanstack/react-query-devtools
```

- [ ] **Step 2: Write `frontend/src/app/queryClient.ts`**

```ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (error instanceof Response && [401, 403, 404].includes(error.status)) return false;
        return failureCount < 2;
      },
    },
  },
});
```

- [ ] **Step 3: Update `frontend/src/main.tsx`**

Wrap the tree with `QueryClientProvider`. Final `main.tsx`:

```tsx
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { RouterProvider } from 'react-router-dom';

import { theme } from './app/theme';
import { router } from './app/router';
import { queryClient } from './app/queryClient';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} defaultColorScheme="light">
        <Notifications position="top-right" />
        <RouterProvider router={router} />
      </MantineProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add tanstack query provider"
```

---

## Task 6: Test harness (Vitest + RTL + MSW)

**Files:**
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/tests/setup.ts`
- Create: `frontend/src/tests/test-utils.tsx`
- Create: `frontend/src/tests/msw/server.ts`
- Create: `frontend/src/tests/msw/handlers.ts`
- Create: `frontend/src/tests/sanity.test.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Install test dependencies**

Run:
```bash
cd frontend && pnpm add -D vitest @vitest/ui @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom msw
```

- [ ] **Step 2: Write `frontend/vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
    css: true,
  },
});
```

- [ ] **Step 3: Write `frontend/src/tests/msw/handlers.ts`**

```ts
import { http, HttpResponse } from 'msw';

export const handlers = [
  // Phase 1 handlers are added in Task 10. Start empty.
  http.get('*/healthz', () => HttpResponse.json({ ok: true })),
];
```

- [ ] **Step 4: Write `frontend/src/tests/msw/server.ts`**

```ts
import { setupServer } from 'msw/node';

import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

- [ ] **Step 5: Write `frontend/src/tests/setup.ts`**

```ts
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { server } from './msw/server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
```

- [ ] **Step 6: Write `frontend/src/tests/test-utils.tsx`**

```tsx
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter, type MemoryRouterProps } from 'react-router-dom';
import type { ReactElement, ReactNode } from 'react';

import { theme } from '@/app/theme';

type Options = RenderOptions & { routerProps?: MemoryRouterProps };

function AllProviders({ children, routerProps }: { children: ReactNode; routerProps?: MemoryRouterProps }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MantineProvider theme={theme} defaultColorScheme="light">
        <MemoryRouter {...routerProps}>{children}</MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui: ReactElement, { routerProps, ...options }: Options = {}) {
  return render(ui, {
    wrapper: ({ children }) => <AllProviders routerProps={routerProps}>{children}</AllProviders>,
    ...options,
  });
}

export * from '@testing-library/react';
```

- [ ] **Step 7: Add `test` script in `frontend/package.json`**

Extend the `scripts` object (keep previous entries):

```json
    "test": "vitest run",
    "test:watch": "vitest",
    "test:ui": "vitest --ui"
```

- [ ] **Step 8: Write a sanity test at `frontend/src/tests/sanity.test.ts`**

```ts
import { describe, it, expect } from 'vitest';

describe('test harness', () => {
  it('runs', () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 9: Run tests**

Run:
```bash
cd frontend && pnpm test
```

Expected: one test passes.

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): add vitest + rtl + msw harness"
```

---

## Task 7: OpenAPI types generation

**Files:**
- Create: `frontend/scripts/generate-types.sh`
- Modify: `frontend/package.json`
- Create: `frontend/src/api/types.gen.ts` (generated, committed)

- [ ] **Step 1: Install `openapi-typescript`**

Run:
```bash
cd frontend && pnpm add -D openapi-typescript
```

- [ ] **Step 2: Write `frontend/scripts/generate-types.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8001}"
OUTPUT="src/api/types.gen.ts"

echo "Generating TypeScript types from $BACKEND_URL/openapi.json -> $OUTPUT"
npx openapi-typescript "$BACKEND_URL/openapi.json" -o "$OUTPUT"
echo "Done."
```

Make it executable:
```bash
chmod +x frontend/scripts/generate-types.sh
```

- [ ] **Step 3: Add `gen:types` script in `frontend/package.json`**

Extend the `scripts` object:

```json
    "gen:types": "./scripts/generate-types.sh"
```

- [ ] **Step 4: Ensure backend is running**

Run in the repo root:
```bash
make up
```

Wait for it to come up. Verify `http://localhost:8001/openapi.json` returns JSON (e.g. `curl -s http://localhost:8001/openapi.json | head`).

- [ ] **Step 5: Generate types**

Run:
```bash
cd frontend && pnpm gen:types
```

Expected: `src/api/types.gen.ts` is created with many `export interface`/`export type` declarations.

- [ ] **Step 6: Typecheck to ensure generated file compiles**

Run:
```bash
cd frontend && pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add openapi type generation"
```

---

## Task 8: `ky` HTTP client (basic)

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Install `ky`**

Run:
```bash
cd frontend && pnpm add ky
```

- [ ] **Step 2: Write failing test `frontend/src/api/client.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';

import { api } from './client';
import { server } from '@/tests/msw/server';

describe('api client', () => {
  it('prefixes requests with /api/v1 by default', async () => {
    let receivedUrl: string | null = null;
    server.use(
      http.get('http://localhost/api/v1/ping', ({ request }) => {
        receivedUrl = request.url;
        return HttpResponse.json({ ok: true });
      }),
    );

    const res = await api.get('ping').json<{ ok: boolean }>();

    expect(receivedUrl).toBe('http://localhost/api/v1/ping');
    expect(res).toEqual({ ok: true });
  });
});
```

- [ ] **Step 3: Run the test, confirm it fails**

Run:
```bash
cd frontend && pnpm test -- client.test
```

Expected: FAIL — `./client` cannot be resolved.

- [ ] **Step 4: Write `frontend/src/api/client.ts`**

```ts
import ky from 'ky';

const prefixUrl =
  (import.meta.env.VITE_API_URL as string | undefined) ?? `${window.location.origin}/api/v1`;

export const api = ky.create({
  prefixUrl,
  timeout: 30_000,
});
```

- [ ] **Step 5: Re-run the test, confirm it passes**

Run:
```bash
cd frontend && pnpm test -- client.test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add ky http client"
```

---

## Task 9: Token storage

**Files:**
- Create: `frontend/src/features/auth/tokenStorage.ts`
- Create: `frontend/src/features/auth/tokenStorage.test.ts`

- [ ] **Step 1: Write failing test `frontend/src/features/auth/tokenStorage.test.ts`**

```ts
import { describe, it, expect, beforeEach } from 'vitest';

import {
  getAccessToken,
  setAccessToken,
  clearAccessToken,
  getRefreshToken,
  setRefreshToken,
  clearRefreshToken,
  clearAllTokens,
} from './tokenStorage';

describe('tokenStorage', () => {
  beforeEach(() => {
    localStorage.clear();
    clearAccessToken();
  });

  it('stores access token in memory', () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken('a.b.c');
    expect(getAccessToken()).toBe('a.b.c');
  });

  it('does not persist access token to localStorage', () => {
    setAccessToken('a.b.c');
    expect(localStorage.getItem('aide.accessToken')).toBeNull();
  });

  it('stores refresh token in localStorage', () => {
    expect(getRefreshToken()).toBeNull();
    setRefreshToken('refresh-xyz');
    expect(getRefreshToken()).toBe('refresh-xyz');
    expect(localStorage.getItem('aide.refreshToken')).toBe('refresh-xyz');
  });

  it('clears access token', () => {
    setAccessToken('a.b.c');
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });

  it('clears refresh token', () => {
    setRefreshToken('r');
    clearRefreshToken();
    expect(getRefreshToken()).toBeNull();
  });

  it('clearAllTokens wipes both', () => {
    setAccessToken('a');
    setRefreshToken('r');
    clearAllTokens();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, confirm it fails**

Run:
```bash
cd frontend && pnpm test -- tokenStorage
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write `frontend/src/features/auth/tokenStorage.ts`**

```ts
const REFRESH_KEY = 'aide.refreshToken';

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_KEY, token);
}

export function clearRefreshToken(): void {
  localStorage.removeItem(REFRESH_KEY);
}

export function clearAllTokens(): void {
  clearAccessToken();
  clearRefreshToken();
}
```

- [ ] **Step 4: Run test, confirm it passes**

Run:
```bash
cd frontend && pnpm test -- tokenStorage
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add token storage"
```

---

## Task 10: Auth endpoint module + MSW handlers

**Files:**
- Create: `frontend/src/api/endpoints/auth.ts`
- Create: `frontend/src/api/endpoints/auth.test.ts`
- Modify: `frontend/src/tests/msw/handlers.ts`

> **Backend contract check (Phase 1 gap flag, from spec section 12):**
> The login route mounts at `/api/v1/login/` (trailing slash; see `backend/api/v1/login.py`). Before running the integration test in this task, confirm the actual paths in the current backend. If `/login/refresh` does not exist, fall back to re-login on expiry instead of auto-refresh (this affects Task 11 test — adjust the mock URL accordingly and document the gap in the PR description).

- [ ] **Step 1: Write `frontend/src/api/endpoints/auth.ts`**

```ts
import { api } from '../client';

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: string;
  email: string;
  is_superuser?: boolean;
}

export async function loginWithPassword(username: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.set('username', username);
  form.set('password', password);
  form.set('grant_type', 'password');

  return api
    .post('login/', {
      body: form,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    .json<LoginResponse>();
}

export async function refreshAccess(refreshToken: string): Promise<LoginResponse> {
  return api
    .post('login/refresh', {
      json: { refresh_token: refreshToken },
    })
    .json<LoginResponse>();
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return api.get('users/me').json<CurrentUser>();
}
```

- [ ] **Step 2: Write failing test `frontend/src/api/endpoints/auth.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';

import { server } from '@/tests/msw/server';

import { loginWithPassword, refreshAccess, getCurrentUser } from './auth';

describe('auth endpoint', () => {
  it('login posts form-urlencoded credentials', async () => {
    let receivedBody: string | null = null;
    let receivedContentType: string | null = null;

    server.use(
      http.post('*/api/v1/login/', async ({ request }) => {
        receivedBody = await request.text();
        receivedContentType = request.headers.get('content-type');
        return HttpResponse.json({
          access_token: 'a.b.c',
          refresh_token: 'r.s.t',
          token_type: 'bearer',
        });
      }),
    );

    const res = await loginWithPassword('alice', 'secret');

    expect(receivedContentType).toMatch(/application\/x-www-form-urlencoded/);
    expect(receivedBody).toContain('username=alice');
    expect(receivedBody).toContain('password=secret');
    expect(receivedBody).toContain('grant_type=password');
    expect(res.access_token).toBe('a.b.c');
    expect(res.refresh_token).toBe('r.s.t');
  });

  it('refresh posts JSON body with refresh_token', async () => {
    let receivedJson: unknown = null;

    server.use(
      http.post('*/api/v1/login/refresh', async ({ request }) => {
        receivedJson = await request.json();
        return HttpResponse.json({
          access_token: 'new',
          refresh_token: 'r2',
          token_type: 'bearer',
        });
      }),
    );

    const res = await refreshAccess('old-refresh');

    expect(receivedJson).toEqual({ refresh_token: 'old-refresh' });
    expect(res.access_token).toBe('new');
  });

  it('getCurrentUser GETs /users/me', async () => {
    server.use(
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide', is_superuser: true }),
      ),
    );

    const me = await getCurrentUser();

    expect(me.email).toBe('alice@aide');
  });
});
```

- [ ] **Step 3: Run tests, confirm pass**

Run:
```bash
cd frontend && pnpm test -- endpoints/auth
```

Expected: 3 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add auth endpoint module"
```

---

## Task 11: Wire auth hooks into `ky` client (bearer + 401 refresh)

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/clientAuth.test.ts`

- [ ] **Step 1: Write failing test `frontend/src/api/clientAuth.test.ts`**

This test covers three scenarios: (a) bearer header is injected when access is set, (b) 401 triggers refresh and one retry, (c) two concurrent 401s share a single refresh call.

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';

import { server } from '@/tests/msw/server';

import { api } from './client';
import {
  clearAllTokens,
  setAccessToken,
  setRefreshToken,
  getAccessToken,
} from '@/features/auth/tokenStorage';

describe('api client auth hooks', () => {
  beforeEach(() => {
    clearAllTokens();
  });

  it('injects Authorization header when access token is present', async () => {
    setAccessToken('current-access');
    let receivedAuth: string | null = null;

    server.use(
      http.get('*/api/v1/things', ({ request }) => {
        receivedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.get('things').json();

    expect(receivedAuth).toBe('Bearer current-access');
  });

  it('omits Authorization header when access token missing', async () => {
    let receivedAuth: string | null = null;

    server.use(
      http.get('*/api/v1/things', ({ request }) => {
        receivedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.get('things').json();

    expect(receivedAuth).toBeNull();
  });

  it('on 401 refreshes access token and retries once', async () => {
    setAccessToken('expired');
    setRefreshToken('valid-refresh');

    let callCount = 0;
    let refreshCallCount = 0;

    server.use(
      http.get('*/api/v1/things', ({ request }) => {
        callCount += 1;
        const auth = request.headers.get('authorization');
        if (auth === 'Bearer expired') {
          return new HttpResponse(null, { status: 401 });
        }
        if (auth === 'Bearer fresh') {
          return HttpResponse.json({ ok: true });
        }
        return new HttpResponse(null, { status: 401 });
      }),
      http.post('*/api/v1/login/refresh', () => {
        refreshCallCount += 1;
        return HttpResponse.json({
          access_token: 'fresh',
          refresh_token: 'new-refresh',
          token_type: 'bearer',
        });
      }),
    );

    const res = await api.get('things').json<{ ok: boolean }>();

    expect(res).toEqual({ ok: true });
    expect(callCount).toBe(2);
    expect(refreshCallCount).toBe(1);
    expect(getAccessToken()).toBe('fresh');
  });

  it('coalesces concurrent refreshes into one', async () => {
    setAccessToken('expired');
    setRefreshToken('valid-refresh');

    let refreshCallCount = 0;
    let thingsCallCount = 0;
    const refreshStarted = vi.fn();

    server.use(
      http.get('*/api/v1/things', ({ request }) => {
        thingsCallCount += 1;
        const auth = request.headers.get('authorization');
        if (auth === 'Bearer fresh') return HttpResponse.json({ ok: true });
        return new HttpResponse(null, { status: 401 });
      }),
      http.post('*/api/v1/login/refresh', async () => {
        refreshCallCount += 1;
        refreshStarted();
        await new Promise((r) => setTimeout(r, 20));
        return HttpResponse.json({
          access_token: 'fresh',
          refresh_token: 'new-refresh',
          token_type: 'bearer',
        });
      }),
    );

    const results = await Promise.all([
      api.get('things').json(),
      api.get('things').json(),
    ]);

    expect(results).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCallCount).toBe(1);
    expect(thingsCallCount).toBe(4); // 2 initial 401s + 2 retries
  });

  it('on refresh failure clears tokens and throws', async () => {
    setAccessToken('expired');
    setRefreshToken('bad-refresh');

    server.use(
      http.get('*/api/v1/things', () => new HttpResponse(null, { status: 401 })),
      http.post('*/api/v1/login/refresh', () => new HttpResponse(null, { status: 401 })),
    );

    await expect(api.get('things').json()).rejects.toThrow();
    expect(getAccessToken()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, confirm it fails**

Run:
```bash
cd frontend && pnpm test -- clientAuth
```

Expected: tests FAIL — no auth hooks wired yet (bearer header missing; refresh doesn't happen).

- [ ] **Step 3: Update `frontend/src/api/client.ts` with auth hooks**

```ts
import ky, { HTTPError } from 'ky';

import {
  clearAllTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from '@/features/auth/tokenStorage';

const prefixUrl =
  (import.meta.env.VITE_API_URL as string | undefined) ?? `${window.location.origin}/api/v1`;

let refreshInFlight: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;
  const refresh = getRefreshToken();
  if (!refresh) throw new Error('No refresh token');

  refreshInFlight = (async () => {
    try {
      const res = await ky.post(`${prefixUrl}/login/refresh`, {
        json: { refresh_token: refresh },
        retry: 0,
      });
      const body = (await res.json()) as {
        access_token: string;
        refresh_token: string;
      };
      setAccessToken(body.access_token);
      setRefreshToken(body.refresh_token);
      return body.access_token;
    } catch (err) {
      clearAllTokens();
      throw err;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

export const api = ky.create({
  prefixUrl,
  timeout: 30_000,
  retry: 0,
  hooks: {
    beforeRequest: [
      (req) => {
        const token = getAccessToken();
        if (token && !req.headers.has('Authorization')) {
          req.headers.set('Authorization', `Bearer ${token}`);
        }
      },
    ],
    afterResponse: [
      async (req, opts, res) => {
        if (res.status !== 401) return res;
        if (req.headers.get('X-Auth-Retry') === '1') return res;

        try {
          const newAccess = await refreshAccessToken();
          const retryReq = new Request(req, {
            headers: {
              ...Object.fromEntries(req.headers),
              Authorization: `Bearer ${newAccess}`,
              'X-Auth-Retry': '1',
            },
          });
          return fetch(retryReq);
        } catch {
          clearAllTokens();
          throw new HTTPError(res, req, opts);
        }
      },
    ],
  },
});
```

- [ ] **Step 4: Run tests, confirm they pass**

Run:
```bash
cd frontend && pnpm test -- clientAuth
```

Expected: 5 tests PASS.

- [ ] **Step 5: Run full test suite + lint + typecheck**

Run:
```bash
cd frontend && pnpm test && pnpm lint && pnpm typecheck
```

Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add bearer + 401 refresh to client"
```

---

## Task 12: `AuthContext` + boot flow

**Files:**
- Create: `frontend/src/features/auth/AuthContext.tsx`
- Create: `frontend/src/features/auth/useAuth.ts`
- Create: `frontend/src/features/auth/AuthContext.test.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Write failing test `frontend/src/features/auth/AuthContext.test.tsx`**

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '@/tests/msw/server';
import { renderWithProviders } from '@/tests/test-utils';
import {
  clearAllTokens,
  getAccessToken,
  setRefreshToken,
} from '@/features/auth/tokenStorage';

import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';

function ProbeComponent() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div>loading</div>;
  if (auth.status === 'anonymous') return <div>anon</div>;
  return (
    <div>
      <span data-testid="user-email">{auth.user.email}</span>
      <button onClick={() => auth.logout()}>logout</button>
    </div>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    clearAllTokens();
  });

  it('starts in loading, resolves to anonymous without stored refresh token', async () => {
    const { getByText } = renderWithProviders(
      <AuthProvider>
        <ProbeComponent />
      </AuthProvider>,
    );

    await waitFor(() => expect(getByText('anon')).toBeInTheDocument());
  });

  it('rehydrates session from stored refresh token', async () => {
    setRefreshToken('valid-refresh');

    server.use(
      http.post('*/api/v1/login/refresh', () =>
        HttpResponse.json({
          access_token: 'hydrated',
          refresh_token: 'valid-refresh-2',
          token_type: 'bearer',
        }),
      ),
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
      ),
    );

    const { getByTestId } = renderWithProviders(
      <AuthProvider>
        <ProbeComponent />
      </AuthProvider>,
    );

    await waitFor(() => expect(getByTestId('user-email')).toHaveTextContent('alice@aide'));
    expect(getAccessToken()).toBe('hydrated');
  });

  it('logout clears tokens and returns to anonymous', async () => {
    setRefreshToken('valid-refresh');

    server.use(
      http.post('*/api/v1/login/refresh', () =>
        HttpResponse.json({
          access_token: 'hydrated',
          refresh_token: 'valid-refresh-2',
          token_type: 'bearer',
        }),
      ),
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
      ),
    );

    const { getByTestId, getByText } = renderWithProviders(
      <AuthProvider>
        <ProbeComponent />
      </AuthProvider>,
    );

    await waitFor(() => expect(getByTestId('user-email')).toBeInTheDocument());

    await userEvent.click(getByText('logout'));

    await waitFor(() => expect(getByText('anon')).toBeInTheDocument());
    expect(getAccessToken()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, confirm it fails**

Run:
```bash
cd frontend && pnpm test -- AuthContext
```

Expected: tests FAIL — module not found.

- [ ] **Step 3: Write `frontend/src/features/auth/AuthContext.tsx`**

```tsx
import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  loginWithPassword,
  refreshAccess,
  getCurrentUser,
  type CurrentUser,
  type LoginResponse,
} from '@/api/endpoints/auth';
import {
  clearAllTokens,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './tokenStorage';

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; user: CurrentUser };

export interface AuthContextValue {
  status: AuthState['status'];
  user: CurrentUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

function applyLogin(res: LoginResponse): void {
  setAccessToken(res.access_token);
  setRefreshToken(res.refresh_token);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const refresh = getRefreshToken();
      if (!refresh) {
        if (!cancelled) setState({ status: 'anonymous' });
        return;
      }

      try {
        const res = await refreshAccess(refresh);
        applyLogin(res);
        const user = await getCurrentUser();
        if (!cancelled) setState({ status: 'authenticated', user });
      } catch {
        clearAllTokens();
        if (!cancelled) setState({ status: 'anonymous' });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await loginWithPassword(username, password);
    applyLogin(res);
    const user = await getCurrentUser();
    setState({ status: 'authenticated', user });
  }, []);

  const logout = useCallback(() => {
    clearAllTokens();
    setState({ status: 'anonymous' });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      user: state.status === 'authenticated' ? state.user : null,
      login,
      logout,
    }),
    [state, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
```

- [ ] **Step 4: Write `frontend/src/features/auth/useAuth.ts`**

```ts
import { useContext } from 'react';

import { AuthContext, type AuthContextValue } from './AuthContext';

type Loading = { status: 'loading' } & Pick<AuthContextValue, 'login' | 'logout'>;
type Anonymous = { status: 'anonymous' } & Pick<AuthContextValue, 'login' | 'logout'>;
type Authenticated = {
  status: 'authenticated';
  user: NonNullable<AuthContextValue['user']>;
} & Pick<AuthContextValue, 'login' | 'logout'>;

export function useAuth(): Loading | Anonymous | Authenticated {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');

  if (ctx.status === 'authenticated' && ctx.user) {
    return { status: 'authenticated', user: ctx.user, login: ctx.login, logout: ctx.logout };
  }
  if (ctx.status === 'loading') {
    return { status: 'loading', login: ctx.login, logout: ctx.logout };
  }
  return { status: 'anonymous', login: ctx.login, logout: ctx.logout };
}
```

- [ ] **Step 5: Update `frontend/src/main.tsx` to mount `AuthProvider`**

The provider must live inside `QueryClientProvider` (so any future query hooks inside auth see the client) and above `RouterProvider`.

```tsx
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { RouterProvider } from 'react-router-dom';

import { theme } from './app/theme';
import { router } from './app/router';
import { queryClient } from './app/queryClient';
import { AuthProvider } from './features/auth/AuthContext';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MantineProvider theme={theme} defaultColorScheme="light">
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </MantineProvider>
      </AuthProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Run tests + typecheck**

Run:
```bash
cd frontend && pnpm test -- AuthContext && pnpm typecheck
```

Expected: tests PASS, typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add auth context + boot flow"
```

---

## Task 13: Notifications helper + `LoginPage`

**Files:**
- Create: `frontend/src/shared/utils/notifications.ts`
- Modify: `frontend/src/features/auth/LoginPage.tsx`
- Create: `frontend/src/features/auth/LoginPage.test.tsx`

- [ ] **Step 1: Install Mantine form + Zod resolver + Zod**

Run:
```bash
cd frontend && pnpm add @mantine/form zod mantine-form-zod-resolver
```

- [ ] **Step 2: Write `frontend/src/shared/utils/notifications.ts`**

```ts
import { notifications } from '@mantine/notifications';

export function notifyError(message: string, title = 'Error') {
  notifications.show({ color: 'red', title, message });
}

export function notifySuccess(message: string, title = 'Success') {
  notifications.show({ color: 'green', title, message });
}
```

- [ ] **Step 3: Write failing test `frontend/src/features/auth/LoginPage.test.tsx`**

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '@/tests/msw/server';
import { renderWithProviders } from '@/tests/test-utils';
import { clearAllTokens, getAccessToken } from '@/features/auth/tokenStorage';

import { AuthProvider } from './AuthContext';
import { LoginPage } from './LoginPage';

function renderLogin() {
  return renderWithProviders(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    clearAllTokens();
  });

  it('shows validation error for empty fields', async () => {
    const { getByRole, findByText } = renderLogin();

    await userEvent.click(getByRole('button', { name: /sign in/i }));

    expect(await findByText(/email is required/i)).toBeInTheDocument();
    expect(await findByText(/password is required/i)).toBeInTheDocument();
  });

  it('on success stores tokens and shows authenticated-ready state', async () => {
    server.use(
      http.post('*/api/v1/login/', () =>
        HttpResponse.json({
          access_token: 'a',
          refresh_token: 'r',
          token_type: 'bearer',
        }),
      ),
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
      ),
    );

    const { getByLabelText, getByRole } = renderLogin();

    await userEvent.type(getByLabelText(/email/i), 'alice@aide');
    await userEvent.type(getByLabelText(/password/i), 'secret');
    await userEvent.click(getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(getAccessToken()).toBe('a'));
  });

  it('on 401 shows error notification, keeps form values', async () => {
    server.use(
      http.post('*/api/v1/login/', () => new HttpResponse(null, { status: 401 })),
    );

    const { getByLabelText, getByRole, findByText } = renderLogin();

    const emailInput = getByLabelText(/email/i) as HTMLInputElement;
    const passwordInput = getByLabelText(/password/i) as HTMLInputElement;

    await userEvent.type(emailInput, 'alice@aide');
    await userEvent.type(passwordInput, 'wrong');
    await userEvent.click(getByRole('button', { name: /sign in/i }));

    expect(await findByText(/invalid credentials/i)).toBeInTheDocument();
    expect(emailInput.value).toBe('alice@aide');
    expect(passwordInput.value).toBe('wrong');
  });
});
```

- [ ] **Step 4: Run test, confirm it fails**

Run:
```bash
cd frontend && pnpm test -- LoginPage
```

Expected: FAIL — `LoginPage` still returns the placeholder.

- [ ] **Step 5: Replace `frontend/src/features/auth/LoginPage.tsx`**

```tsx
import { Button, Paper, PasswordInput, Stack, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { notifyError } from '@/shared/utils/notifications';

import { useAuth } from './useAuth';

const schema = z.object({
  email: z.string().min(1, 'Email is required').email('Must be a valid email'),
  password: z.string().min(1, 'Password is required'),
});

type Values = z.infer<typeof schema>;

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<Values>({
    initialValues: { email: '', password: '' },
    validate: zodResolver(schema),
  });

  async function onSubmit(values: Values) {
    setSubmitting(true);
    try {
      await auth.login(values.email, values.password);
      navigate('/');
    } catch (err) {
      const status = err instanceof Error && 'response' in err ? (err as { response?: { status?: number } }).response?.status : undefined;
      notifyError(status === 401 ? 'Invalid credentials' : 'Login failed — please try again');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack align="center" justify="center" mih="100vh" p="md">
      <Paper withBorder p="xl" w={360}>
        <Title order={2} mb="lg">
          Sign in
        </Title>
        <form onSubmit={form.onSubmit(onSubmit)}>
          <Stack>
            <TextInput
              label="Email"
              placeholder="you@aide"
              autoComplete="username"
              {...form.getInputProps('email')}
            />
            <PasswordInput
              label="Password"
              autoComplete="current-password"
              {...form.getInputProps('password')}
            />
            <Button type="submit" loading={submitting} fullWidth>
              Sign in
            </Button>
          </Stack>
        </form>
      </Paper>
    </Stack>
  );
}
```

- [ ] **Step 6: Run tests**

Run:
```bash
cd frontend && pnpm test -- LoginPage
```

Expected: 3 tests PASS.

- [ ] **Step 7: Typecheck + lint**

Run:
```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add login page"
```

---

## Task 14: `RequireAuth` guard

**Files:**
- Create: `frontend/src/features/auth/RequireAuth.tsx`
- Create: `frontend/src/features/auth/RequireAuth.test.tsx`

- [ ] **Step 1: Write failing test `frontend/src/features/auth/RequireAuth.test.tsx`**

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import { waitFor } from '@testing-library/react';

import { server } from '@/tests/msw/server';
import { renderWithProviders } from '@/tests/test-utils';
import { clearAllTokens, setRefreshToken } from '@/features/auth/tokenStorage';

import { AuthProvider } from './AuthContext';
import { RequireAuth } from './RequireAuth';

function Tree() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<div>login-page</div>} />
        <Route path="/" element={<RequireAuth>home-content</RequireAuth>} />
      </Routes>
    </AuthProvider>
  );
}

describe('RequireAuth', () => {
  beforeEach(() => clearAllTokens());

  it('redirects to /login when unauthenticated', async () => {
    const { findByText } = renderWithProviders(<Tree />, {
      routerProps: { initialEntries: ['/'] },
    });

    expect(await findByText('login-page')).toBeInTheDocument();
  });

  it('renders children when authenticated', async () => {
    setRefreshToken('valid-refresh');
    server.use(
      http.post('*/api/v1/login/refresh', () =>
        HttpResponse.json({
          access_token: 'a',
          refresh_token: 'r',
          token_type: 'bearer',
        }),
      ),
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
      ),
    );

    const { findByText } = renderWithProviders(<Tree />, {
      routerProps: { initialEntries: ['/'] },
    });

    await waitFor(() => expect(findByText('home-content')).resolves.toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test, confirm fail**

Run:
```bash
cd frontend && pnpm test -- RequireAuth
```

Expected: FAIL.

- [ ] **Step 3: Write `frontend/src/features/auth/RequireAuth.tsx`**

```tsx
import { Center, Loader } from '@mantine/core';
import { type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

import { useAuth } from './useAuth';

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.status === 'loading') {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  if (auth.status === 'anonymous') {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
```

- [ ] **Step 4: Run test, confirm pass**

Run:
```bash
cd frontend && pnpm test -- RequireAuth
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add require-auth guard"
```

---

## Task 15: `AppShell` + `TopBar` + `SideNav`

**Files:**
- Create: `frontend/src/app/layout/AppShell.tsx`
- Create: `frontend/src/app/layout/TopBar.tsx`
- Create: `frontend/src/app/layout/SideNav.tsx`
- Create: `frontend/src/app/layout/AppShell.test.tsx`

- [ ] **Step 1: Write failing test `frontend/src/app/layout/AppShell.test.tsx`**

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { waitFor } from '@testing-library/react';
import { Outlet, Routes, Route } from 'react-router-dom';

import { server } from '@/tests/msw/server';
import { renderWithProviders } from '@/tests/test-utils';
import { AuthProvider } from '@/features/auth/AuthContext';
import {
  clearAllTokens,
  getAccessToken,
  setRefreshToken,
} from '@/features/auth/tokenStorage';

import { AppShell } from './AppShell';

function authenticatedApp() {
  setRefreshToken('valid-refresh');
  server.use(
    http.post('*/api/v1/login/refresh', () =>
      HttpResponse.json({
        access_token: 'a',
        refresh_token: 'r',
        token_type: 'bearer',
      }),
    ),
    http.get('*/api/v1/users/me', () =>
      HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
    ),
  );
}

function Tree() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<div>login-page</div>} />
        <Route path="/" element={<AppShell />}>
          <Route index element={<div>inner-home</div>} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

describe('AppShell', () => {
  beforeEach(() => clearAllTokens());

  it('renders logo, user email, and outlet content', async () => {
    authenticatedApp();

    const { findByText } = renderWithProviders(<Tree />, {
      routerProps: { initialEntries: ['/'] },
    });

    expect(await findByText('AIDE')).toBeInTheDocument();
    expect(await findByText('alice@aide')).toBeInTheDocument();
    expect(await findByText('inner-home')).toBeInTheDocument();
  });

  it('logout returns user to /login and clears tokens', async () => {
    authenticatedApp();

    const { findByText, findByRole } = renderWithProviders(<Tree />, {
      routerProps: { initialEntries: ['/'] },
    });

    await findByText('inner-home');

    const menuButton = await findByRole('button', { name: /alice@aide/i });
    await userEvent.click(menuButton);

    const logoutItem = await findByRole('menuitem', { name: /log out/i });
    await userEvent.click(logoutItem);

    await waitFor(() => expect(findByText('login-page')).resolves.toBeInTheDocument());
    expect(getAccessToken()).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, confirm fail**

Run:
```bash
cd frontend && pnpm test -- AppShell
```

Expected: FAIL — component missing.

- [ ] **Step 3: Write `frontend/src/app/layout/SideNav.tsx`**

Stub with placeholder links — replaced fully in Phase 2.

```tsx
import { Stack, NavLink } from '@mantine/core';
import { Link, useLocation } from 'react-router-dom';

const STUB_LINKS = [
  { label: 'Home', to: '/' },
  { label: 'Systems', to: '/systems' },
  { label: 'Crawls', to: '/crawls' },
  { label: 'Admin', to: '/admin' },
];

export function SideNav() {
  const { pathname } = useLocation();
  return (
    <Stack gap={2} p="sm">
      {STUB_LINKS.map((l) => (
        <NavLink
          key={l.to}
          component={Link}
          to={l.to}
          label={l.label}
          active={pathname === l.to || (l.to !== '/' && pathname.startsWith(l.to))}
        />
      ))}
    </Stack>
  );
}
```

- [ ] **Step 4: Write `frontend/src/app/layout/TopBar.tsx`**

```tsx
import { Group, Menu, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconLogout } from '@tabler/icons-react';

import { useAuth } from '@/features/auth/useAuth';

export function TopBar() {
  const auth = useAuth();
  if (auth.status !== 'authenticated') return null;

  return (
    <Group justify="space-between" px="md" h="100%">
      <Text fw={700} size="lg">
        AIDE
      </Text>
      <Menu position="bottom-end" withinPortal>
        <Menu.Target>
          <UnstyledButton aria-label={auth.user.email}>
            <Group gap="xs">
              <Text size="sm">{auth.user.email}</Text>
              <IconChevronDown size={14} />
            </Group>
          </UnstyledButton>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconLogout size={14} />} onClick={auth.logout}>
            Log out
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
```

- [ ] **Step 5: Write `frontend/src/app/layout/AppShell.tsx`**

```tsx
import { AppShell as MantineAppShell } from '@mantine/core';
import { Outlet } from 'react-router-dom';

import { RequireAuth } from '@/features/auth/RequireAuth';

import { SideNav } from './SideNav';
import { TopBar } from './TopBar';

export function AppShell() {
  return (
    <RequireAuth>
      <MantineAppShell
        header={{ height: 56 }}
        navbar={{ width: 220, breakpoint: 'sm' }}
        padding="md"
      >
        <MantineAppShell.Header>
          <TopBar />
        </MantineAppShell.Header>
        <MantineAppShell.Navbar>
          <SideNav />
        </MantineAppShell.Navbar>
        <MantineAppShell.Main>
          <Outlet />
        </MantineAppShell.Main>
      </MantineAppShell>
    </RequireAuth>
  );
}
```

- [ ] **Step 6: Run test**

Run:
```bash
cd frontend && pnpm test -- AppShell
```

Expected: 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add app shell + topbar + sidenav"
```

---

## Task 16: `HomePage`

**Files:**
- Modify: `frontend/src/features/home/HomePage.tsx`

- [ ] **Step 1: Replace `frontend/src/features/home/HomePage.tsx`**

```tsx
import { Stack, Text, Title } from '@mantine/core';

import { useAuth } from '@/features/auth/useAuth';

export function HomePage() {
  const auth = useAuth();
  const name = auth.status === 'authenticated' ? auth.user.email : '';

  return (
    <Stack gap="sm">
      <Title order={2}>Welcome{name ? `, ${name}` : ''}</Title>
      <Text c="dimmed">
        This is the AIDE Metastore. Phase 2 will add the Systems list. For now, explore the side
        navigation.
      </Text>
    </Stack>
  );
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add home page stub"
```

---

## Task 17: Wire the final route tree + end-to-end test

**Files:**
- Modify: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/router.test.tsx`

- [ ] **Step 1: Rewrite `frontend/src/app/router.tsx`**

```tsx
import { createBrowserRouter } from 'react-router-dom';

import { AppShell } from './layout/AppShell';
import { HomePage } from '@/features/home/HomePage';
import { LoginPage } from '@/features/auth/LoginPage';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <AppShell />,
    children: [{ index: true, element: <HomePage /> }],
  },
  { path: '*', element: <div>404</div> },
]);
```

- [ ] **Step 2: Write end-to-end test `frontend/src/app/router.test.tsx`**

Covers the Phase 1 success criterion: unauthenticated visitor → login form → submit → authenticated home page.

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';

import { server } from '@/tests/msw/server';
import { renderWithProviders } from '@/tests/test-utils';
import { AuthProvider } from '@/features/auth/AuthContext';
import { clearAllTokens } from '@/features/auth/tokenStorage';
import { LoginPage } from '@/features/auth/LoginPage';
import { AppShell } from '@/app/layout/AppShell';
import { HomePage } from '@/features/home/HomePage';

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<AppShell />}>
          <Route index element={<HomePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

describe('router end-to-end', () => {
  beforeEach(() => clearAllTokens());

  it('logs in from /login and lands on authenticated home', async () => {
    server.use(
      http.post('*/api/v1/login/', () =>
        HttpResponse.json({
          access_token: 'a',
          refresh_token: 'r',
          token_type: 'bearer',
        }),
      ),
      http.get('*/api/v1/users/me', () =>
        HttpResponse.json({ id: 'u1', email: 'alice@aide' }),
      ),
    );

    const { findByText, getByLabelText, getByRole, findByRole } = renderWithProviders(<App />, {
      routerProps: { initialEntries: ['/'] },
    });

    // Initial nav guard bounces us to /login
    expect(await findByRole('button', { name: /sign in/i })).toBeInTheDocument();

    await userEvent.type(getByLabelText(/email/i), 'alice@aide');
    await userEvent.type(getByLabelText(/password/i), 'secret');
    await userEvent.click(getByRole('button', { name: /sign in/i }));

    await waitFor(async () => expect(await findByText(/welcome/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 3: Run the full test suite**

Run:
```bash
cd frontend && pnpm test
```

Expected: all tests PASS.

- [ ] **Step 4: Lint + typecheck**

Run:
```bash
cd frontend && pnpm lint && pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 5: Manual smoke test against real backend**

With `make up` running, start the dev server:

```bash
cd frontend && pnpm dev
```

- Open `http://localhost:5173/` → redirects to `/login`.
- Enter the superuser credentials (see `backend/.env` or the init script). Submit.
- Land on `/` with the side nav and "Welcome, \<email\>" greeting.
- Click the user menu → "Log out" → back to `/login`.
- Reload `/` while logged in → stays on `/` (refresh flow rehydrated the session).

Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): wire final route tree + e2e test"
```

---

## Phase 1 exit checklist

- [ ] `pnpm lint && pnpm typecheck && pnpm test` pass in `frontend/`.
- [ ] Manual smoke test (Task 17 Step 5) passes against a real backend.
- [ ] 7-phase roadmap remains accurate — no discoveries invalidated phase 2+ assumptions. If any did, update `docs/superpowers/plans/2026-04-15-frontend-roadmap.md`.
- [ ] Open questions from spec section 12 revisited:
  - `/login/refresh` route confirmed present (or gap documented + fallback implemented).
  - `PaginatedResponse_<T>_` structure inspected in `types.gen.ts` for later phases.
