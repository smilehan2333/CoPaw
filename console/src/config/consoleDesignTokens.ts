export const CONSOLE_BASE_TOKENS = {
  colorSuccess: "#2F7D5B",
  colorWarning: "#A56A24",
  colorError: "#B94A4F",

  radiusControl: 8,
  radiusPanel: 12,
  radiusSmall: 6,

  shadowSurface: "0 1px 2px rgba(29, 36, 51, 0.05)",
  shadowOverlay: "0 14px 36px rgba(29, 36, 51, 0.14)",

  transitionFast: "160ms ease",
} as const;

export const CONSOLE_MANAGEMENT_TOKENS = {
  colorCanvas: "#FFFFFF",
  colorSurface: "#FFFFFF",
  colorSurfaceSubtle: "#F7F9FC",
  colorNavigation: "#FFFFFF",
  colorBorder: "#E5E7EB",
  colorBorderStrong: "#D0D7E2",
  colorText: "#111827",
  colorTextSecondary: "#4B5563",
  colorTextMuted: "#8A94A6",
  colorPrimary: "#3769FC",
  colorPrimaryHover: "#2957DC",
  colorPrimarySoft: "#EEF4FF",

  fontUi: '"Segoe UI", "Microsoft YaHei", "PingFang SC", "Helvetica Neue", sans-serif',
  fontEditorial: 'Georgia, "Songti SC", "SimSun", serif',
  fontMono: 'SFMono-Regular, Consolas, "Liberation Mono", monospace',

  providerCardWidth: 480,
} as const;

export const CONSOLE_CONVERSATION_TOKENS = {
  colorPrimary: "#3769FC",
} as const;

// Compatibility export for existing calibrated surfaces. New code should use
// the explicit base, management, or conversation token group above.
export const CONSOLE_DESIGN_TOKENS = {
  ...CONSOLE_BASE_TOKENS,
  ...CONSOLE_MANAGEMENT_TOKENS,
  colorConversationPrimary: CONSOLE_CONVERSATION_TOKENS.colorPrimary,
} as const;

const CONSOLE_CSS_VARIABLES = {
  "--console-font-ui": CONSOLE_MANAGEMENT_TOKENS.fontUi,
  "--console-font-editorial": CONSOLE_MANAGEMENT_TOKENS.fontEditorial,
  "--console-font-mono": CONSOLE_MANAGEMENT_TOKENS.fontMono,
  "--console-management-canvas": CONSOLE_MANAGEMENT_TOKENS.colorCanvas,
  "--console-management-surface": CONSOLE_MANAGEMENT_TOKENS.colorSurface,
  "--console-management-surface-subtle":
    CONSOLE_MANAGEMENT_TOKENS.colorSurfaceSubtle,
  "--console-management-navigation": CONSOLE_MANAGEMENT_TOKENS.colorNavigation,
  "--console-management-border": CONSOLE_MANAGEMENT_TOKENS.colorBorder,
  "--console-management-border-strong":
    CONSOLE_MANAGEMENT_TOKENS.colorBorderStrong,
  "--console-management-text": CONSOLE_MANAGEMENT_TOKENS.colorText,
  "--console-management-text-secondary":
    CONSOLE_MANAGEMENT_TOKENS.colorTextSecondary,
  "--console-management-text-muted": CONSOLE_MANAGEMENT_TOKENS.colorTextMuted,
  "--console-management-primary": CONSOLE_MANAGEMENT_TOKENS.colorPrimary,
  "--console-management-primary-hover":
    CONSOLE_MANAGEMENT_TOKENS.colorPrimaryHover,
  "--console-management-primary-soft":
    CONSOLE_MANAGEMENT_TOKENS.colorPrimarySoft,
  "--console-management-success": CONSOLE_BASE_TOKENS.colorSuccess,
  "--console-management-warning": CONSOLE_BASE_TOKENS.colorWarning,
  "--console-management-error": CONSOLE_BASE_TOKENS.colorError,
  "--console-management-shadow": CONSOLE_BASE_TOKENS.shadowSurface,
  "--console-management-shadow-raised": CONSOLE_BASE_TOKENS.shadowOverlay,
  "--console-conversation-primary": CONSOLE_CONVERSATION_TOKENS.colorPrimary,
} as const;

export function applyConsoleDesignTokens(
  root: HTMLElement = document.documentElement,
): void {
  Object.entries(CONSOLE_CSS_VARIABLES).forEach(([property, value]) => {
    root.style.setProperty(property, String(value));
  });
}
