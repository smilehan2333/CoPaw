import type { MarketSkill, MarketSkillDetail } from "../../api/modules/market";

const SKILL_READINESS_ID_PATTERN = /^[\p{L}\p{N}_.:-]+$/u;

export interface SkillReadinessTarget {
  skillId: string;
  displayName: string;
  idSource: "skill_id" | "skill_name";
  valid: boolean;
}

function normalizeSkillReadinessId(value: string | null | undefined): string {
  return String(value || "").trim();
}

export function resolveSkillReadinessTarget(
  skill: MarketSkill | MarketSkillDetail | null,
): SkillReadinessTarget {
  const displayName = skill?.chinese_name?.trim() || skill?.name || "";
  const explicitSkillId = normalizeSkillReadinessId(skill?.skill_id);
  const fallbackSkillName = normalizeSkillReadinessId(
    skill?.skill_name || skill?.name,
  );
  const skillId = explicitSkillId || fallbackSkillName;
  return {
    skillId,
    displayName,
    idSource: explicitSkillId ? "skill_id" : "skill_name",
    valid: Boolean(skillId && SKILL_READINESS_ID_PATTERN.test(skillId)),
  };
}
