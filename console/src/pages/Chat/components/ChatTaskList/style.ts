import { createGlobalStyle } from "antd-style";
import { DESIGN_TOKENS } from "@/config/designTokens";

export default createGlobalStyle`
.chat-task-list {
  padding: 0 20px;
  margin-bottom: 8px;

  &-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 21px;
    margin-bottom: 6px;
    cursor: pointer;
  }

  &-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    font-weight: 500;
    color: ${DESIGN_TOKENS.colorTextPrimary};
  }

  &-toggle {
    width: 10px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: ${DESIGN_TOKENS.colorTextMuted};
    transition: transform 0.2s ease;

    &--collapsed {
      transform: rotate(-90deg);
    }
  }

  &-items {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &-item {
    position: relative;
    padding: 8px 12px;
    cursor: pointer;
    border-radius: 4px;
    background-color: transparent;
    transition: background-color 0.15s ease;
    overflow: hidden;

    &:hover {
      background: rgba(55, 105, 252, 0.04);
    }

    &--paused {
      background: rgba(223, 146, 33, 0.06);
    }

    &--running {
      background: rgba(55, 105, 252, 0.06);
    }

    &--selected {
      background: rgba(55, 105, 252, 0.10);

      &::before {
        content: "";
        position: absolute;
        left: 0;
        top: 4px;
        bottom: 4px;
        width: 3px;
        border-radius: 0 2px 2px 0;
        background-color: #3769FC;
      }
    }
  }

  &-item-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 2px;
  }

  &-item-title {
    font-size: 14px;
    line-height: 20px;
    font-weight: 500;
    color: ${DESIGN_TOKENS.colorTextPrimary};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }

  &-item-badge {
    flex-shrink: 0;
    min-width: 14px;
    height: 14px;
    padding: 0 4px;
    border-radius: 7px;
    background-color: ${DESIGN_TOKENS.colorBadgeRed};
    color: #FFFFFF;
    font-size: 10px;
    line-height: 14px;
    text-align: center;
  }

  &-item-trailing {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
  }

  &-item-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    flex: 0 0 auto;
    opacity: 1;
    pointer-events: auto;
  }

  &-item-action-trigger {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: ${DESIGN_TOKENS.colorTextMuted};
    cursor: pointer;
    transition:
      background-color 0.15s ease,
      color 0.15s ease;

    &:hover,
    &--open {
      background: rgba(132, 130, 231, 0.14);
      color: ${DESIGN_TOKENS.colorPrimary};
    }

    &:focus-visible {
      outline: 2px solid rgba(55, 105, 252, 0.32);
      outline-offset: 2px;
    }
  }

  &-item-status {
    margin-bottom: 4px;
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;

    &--auto {
      color: #A15C07;
    }

    &--manual {
      color: ${DESIGN_TOKENS.colorTextMuted};
    }

  }

  &-item-subtitle {
    font-size: 12px;
    line-height: 16px;
    color: ${DESIGN_TOKENS.colorTextMuted};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &-item-next-run {
    margin-top: 4px;
    font-size: 12px;
    line-height: 16px;
    color: ${DESIGN_TOKENS.colorTextSecondary};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &-item-time {
    margin-right: 8px;
    color: ${DESIGN_TOKENS.colorTextMuted};
  }

  &-paused-group {
    margin: 1px 0 4px;
  }

  &-paused-toggle {
    width: 100%;
    min-height: 22px;
    padding: 4px 8px 0;
    display: flex;
    align-items: center;
    gap: 6px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: ${DESIGN_TOKENS.colorTextMuted};
    font-size: 12px;
    line-height: 18px;
    text-align: left;
    cursor: pointer;
    transition: color 0.15s ease;

    &::after {
      content: "";
      height: 1px;
      flex: 1 1 auto;
      margin-left: 4px;
      background: rgba(17, 20, 45, 0.06);
    }

    &:hover {
      color: ${DESIGN_TOKENS.colorTextSecondary};
    }

    &:focus-visible {
      outline: 2px solid rgba(55, 105, 252, 0.32);
      outline-offset: 1px;
    }

    .chat-task-list-toggle {
      flex: 0 0 auto;
    }
  }

  &-paused-label {
    min-width: 0;
    color: inherit;
    font-weight: 400;
  }

  &-paused-count {
    flex: 0 0 auto;
    color: inherit;
    font-size: 12px;
    font-weight: 400;
    line-height: 18px;
    font-variant-numeric: tabular-nums;
    margin-left: -4px;
  }

  &-paused-items {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 4px;

    &[hidden] {
      display: none;
    }
  }

  &-empty {
    min-height: 116px;
    padding: 24px 16px;
    border-radius: ${DESIGN_TOKENS.radiusCard}px;
    background: rgba(55, 105, 252, 0.035);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
  }

  &-empty-title {
    color: ${DESIGN_TOKENS.colorTextMuted};
    font-size: 14px;
    font-weight: 500;
    line-height: 20px;
  }

  &-empty-description {
    margin-top: 12px;
    color: ${DESIGN_TOKENS.colorTextMuted};
    font-size: 13px;
    line-height: 20px;
  }
}

/* Dark mode support */
.dark-mode .chat-task-list-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.dark-mode .chat-task-list-item--selected {
  background: rgba(255, 255, 255, 0.12);
}

.dark-mode .chat-task-list-item--selected::before {
  background-color: #5B8AFF;
}

.dark-mode .chat-task-list-paused-toggle {
  color: rgba(255, 255, 255, 0.46);
}

.dark-mode .chat-task-list-paused-toggle:hover {
  color: rgba(255, 255, 255, 0.70);
}

.dark-mode .chat-task-list-paused-toggle::after {
  background: rgba(255, 255, 255, 0.08);
}

@media (prefers-reduced-motion: reduce) {
  .chat-task-list-toggle,
  .chat-task-list-paused-toggle {
    transition: none;
  }
}
`;
