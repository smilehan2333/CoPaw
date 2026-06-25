---
name: copaw-f2e-review
description: CoPaw-adapted frontend quality review for React, TypeScript, hooks, forms, tables, dialogs, API adapters, and visible Console UI work under console/. Use when writing, reviewing, or refactoring CoPaw frontend code; apply after the user request, AGENTS.md, console/DESIGN.md, existing ESLint, TypeScript, Prettier, tests, and local code style.
---

# CoPaw F2E Review

Use this skill as a lightweight frontend quality gate inspired by Alibaba F2E Spec. It supplements CoPaw's local rules; it does not replace project design, workflow, formatting, or tooling decisions.

## Priority

Follow these authorities in order:

1. User request.
2. Repository `AGENTS.md` and more specific directory instructions.
3. `console/DESIGN.md` for visible Console UI under `console/`.
4. Existing TypeScript, ESLint, Prettier, test, and local code patterns.
5. This checklist.

If this skill conflicts with CoPaw design rules, established formatter output, or existing project conventions, CoPaw wins.

## Scope

Apply this checklist to frontend work under `console/`, especially:

- React components and custom hooks.
- TypeScript utilities, stores, request adapters, and route logic used by the Console.
- Forms, tables, dialogs, drawers, filters, empty states, loading states, error states, and permission-limited UI.
- UI-only changes that must preserve API contracts, route paths, iframe messages, state semantics, validation, error handling, and business outcomes.

Do not use this skill to introduce new visual direction, broad restyling, design-system rules, or new lint tooling. Those changes must follow the repository workflow.

## Review Checklist

### React And TypeScript

- Prefer `const`; use `let` only for reassignment. Do not introduce `var`.
- Keep imports at the top and avoid duplicate imports from the same module.
- Use TypeScript types and existing project patterns instead of PropTypes/defaultProps.
- Keep components and hooks focused, but do not force one React component per file when local helper components improve readability.
- Follow React Hooks rules: call hooks only at the top level of React components or custom hooks, name custom hooks with `use`, and include complete dependencies.
- Use stable list keys. Avoid index keys when items can be inserted, removed, filtered, or reordered.
- Avoid unnecessary re-renders with `memo`, `useMemo`, or `useCallback` only when they reduce real churn or preserve stable references used by child components/hooks.
- Preserve current API request parameters, route paths, permissions, iframe contracts, Zustand state meaning, and event outcomes unless the accepted requirement says otherwise.

### Code Quality

- Keep functions readable and narrow; extract helpers only when they clarify real branching or reuse.
- Avoid mutating function parameters unless the surrounding code clearly uses that pattern.
- Prefer destructuring and object/array spread when they improve clarity.
- Use strict equality and explicit null/undefined handling.
- Keep user-facing strings, Chinese text, IDs, URLs, model names, and paths resilient to long values.
- Leave comments only for non-obvious intent, constraints, or integration contracts.

### Safety And Accessibility

- Do not introduce `eval`, production `debugger`, or noisy `console` calls.
- Avoid `dangerouslySetInnerHTML`; when unavoidable, sanitize input and keep the reason visible in code.
- Add `rel="noopener noreferrer"` for external links using `target="_blank"`.
- Use accessible labels for form controls; placeholders are not labels.
- Keep keyboard focus visible and preserve disabled, loading, empty, error, unavailable, success, destructive, and in-progress states when applicable.
- Ensure dynamic states are distinguishable without relying only on color.

### Console UI Fit

- Read `console/DESIGN.md` before visible UI work and apply it to the changed surface.
- Use existing shared components, Ant Design/AgentScope patterns already present, `lucide-react` where appropriate, and `console/src/config/consoleDesignTokens.ts` for reusable visual roles.
- Preserve the light Management Console direction, the Conversation Workspace `#3769FC` emphasis, and the `hideMenu=true` embedded-mode contract where applicable.
- Do not add competing design manuals, broad global restyles, hover-only primary actions, nested decorative cards, generic hero layouts, decorative gradients, or one-note palettes.
- Check real-data resilience: long Chinese names, long English identifiers, provider URLs, IDs, empty values, large counts, many rows, and narrow embedded containers.

## Verification

Before finishing frontend changes, run the relevant existing checks for the changed surface when feasible:

- `npm run lint`
- `npm run format:check`
- `npm run test:run`
- `npm run build`

For visible UI changes, also perform the repository-required UI review for the affected surface and report any verification that could not be completed.
