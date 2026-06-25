import { describe, expect, it } from "vitest";
import { resolveSkillReadinessTarget } from "./skillReadiness";

describe("skillReadiness", () => {
  it("uses skill_id before skill_name", () => {
    expect(
      resolveSkillReadinessTarget({
        item_id: "market-1",
        skill_id: "skill-001",
        name: "Display Name",
        skill_name: "stable-name",
        description: "",
        version: "1.0.0",
        creator_id: "admin",
        creator_name: "Admin",
        category_id: null,
        bbk_ids: [],
        status: "active",
        created_at: null,
        updated_at: null,
        call_count: 0,
        user_count: 0,
      }),
    ).toMatchObject({
      skillId: "skill-001",
      idSource: "skill_id",
      valid: true,
    });
  });

  it("accepts Chinese skill ids", () => {
    expect(
      resolveSkillReadinessTarget({
        item_id: "market-1",
        skill_id: "存款到期客户评分",
        name: "Display Name",
        skill_name: "stable-name",
        description: "",
        version: "1.0.0",
        creator_id: "admin",
        creator_name: "Admin",
        category_id: null,
        bbk_ids: [],
        status: "active",
        created_at: null,
        updated_at: null,
        call_count: 0,
        user_count: 0,
      }),
    ).toMatchObject({
      skillId: "存款到期客户评分",
      idSource: "skill_id",
      valid: true,
    });
  });

  it("falls back to skill_name when skill_id is missing", () => {
    expect(
      resolveSkillReadinessTarget({
        item_id: "market-1",
        name: "Display Name",
        skill_name: "stable-name",
        description: "",
        version: "1.0.0",
        creator_id: "admin",
        creator_name: "Admin",
        category_id: null,
        bbk_ids: [],
        status: "active",
        created_at: null,
        updated_at: null,
        call_count: 0,
        user_count: 0,
      }),
    ).toMatchObject({
      skillId: "stable-name",
      idSource: "skill_name",
      valid: true,
    });
  });

  it("marks unsupported fallback ids invalid before requesting backend", () => {
    expect(
      resolveSkillReadinessTarget({
        item_id: "market-1",
        name: "bad skill name",
        description: "",
        version: "1.0.0",
        creator_id: "admin",
        creator_name: "Admin",
        category_id: null,
        bbk_ids: [],
        status: "active",
        created_at: null,
        updated_at: null,
        call_count: 0,
        user_count: 0,
      }).valid,
    ).toBe(false);
  });
});
