import type { IAgentScopeRuntimeWebUISession } from "@/components/agentscope-chat";

type SessionWithIdentity = IAgentScopeRuntimeWebUISession & {
  realId?: string;
  sessionId?: string;
};

type SessionIdentity = Partial<SessionWithIdentity> & {
  id?: string;
};

function identityKeys(session: SessionIdentity): string[] {
  return [session.id, session.realId, session.sessionId].filter(
    (value): value is string => Boolean(value),
  );
}

function sessionsMatch(
  left: IAgentScopeRuntimeWebUISession,
  right: IAgentScopeRuntimeWebUISession,
): boolean {
  const rightKeys = new Set(identityKeys(right));
  return identityKeys(left).some((key) => rightKeys.has(key));
}

function hasExcludedIdentity(
  session: IAgentScopeRuntimeWebUISession,
  excludedIdentityKeys: ReadonlySet<string>,
): boolean {
  return identityKeys(session).some((key) => excludedIdentityKeys.has(key));
}

export function mergeConcurrentSessions(
  incoming: IAgentScopeRuntimeWebUISession[],
  current: IAgentScopeRuntimeWebUISession[],
  preserveCurrentDetails: boolean,
  excludedSessions: SessionIdentity[] = [],
): IAgentScopeRuntimeWebUISession[] {
  const excludedIdentityKeys = new Set(excludedSessions.flatMap(identityKeys));
  const currentOnly = current.filter(
    (currentSession) =>
      !hasExcludedIdentity(currentSession, excludedIdentityKeys) &&
      !incoming.some((incomingSession) =>
        sessionsMatch(currentSession, incomingSession),
      ),
  );
  const mergedIncoming = incoming.map((incomingSession) => {
    const currentSession = current.find((candidate) =>
      sessionsMatch(candidate, incomingSession),
    );
    if (!currentSession) return incomingSession;

    const merged = preserveCurrentDetails
      ? { ...incomingSession, ...currentSession }
      : { ...currentSession, ...incomingSession };
    merged.messages = currentSession.messages;
    if (Object.prototype.hasOwnProperty.call(currentSession, "generating")) {
      merged.generating = currentSession.generating;
    }
    return merged;
  });

  return [...currentOnly, ...mergedIncoming];
}
