import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import type { CronJobSpecOutput } from "@/api/types";
import {
  buildCronJobFormValues,
  buildCronJobSubmitPayload,
  getBroadcastResultMessage,
  normalizeSkillIdsInput,
} from "./helpers";

function buildCronJob(
  overrides: Partial<CronJobSpecOutput> = {},
): CronJobSpecOutput {
  return {
    id: "job-1",
    name: "test job",
    enabled: true,
    schedule: {
      type: "cron",
      cron: "00 09 * * 1,3",
      timezone: "UTC",
    },
    task_type: "agent",
    request: {
      input: [{ role: "user", content: [{ type: "text", text: "hello" }] }],
      session_id: "session-1",
      user_id: "user-1",
    },
    dispatch: {
      type: "channel",
      channel: "console",
      target: {
        user_id: "user-1",
        session_id: "session-1",
      },
      mode: "final",
    },
    runtime: {
      max_concurrency: 1,
    },
    meta: {},
    ...overrides,
  };
}

describe("CronJobs helpers", () => {
  it("hydrates edit form values with execution_model_key and parsed cron fields", () => {
    const job = buildCronJob({
      model_slot: {
        provider_id: "openai",
        model: "gpt-5.4",
      },
    });

    const result = buildCronJobFormValues(job);

    expect(result.execution_model_key).toBe("openai::gpt-5.4");
    expect(result.request?.input).toBe(
      JSON.stringify(job.request?.input, null, 2),
    );
    expect(dayjs.isDayjs(result.cronTime)).toBe(true);
    expect(result.cronTime?.hour()).toBe(9);
    expect(result.cronTime?.minute()).toBe(0);
    expect(result.cronDaysOfWeek).toEqual(["mon", "wed"]);
  });

  it("hydrates notification delay as hours when stored minutes divide by 60", () => {
    const result = buildCronJobFormValues(
      buildCronJob({
        meta: {
          notification_delay_minutes: 120,
        },
      }),
    );

    expect(result.notificationDelayValue).toBe(2);
    expect(result.notificationDelayUnit).toBe("hours");
  });

  it("builds submit payload with explicit model_slot for agent jobs", () => {
    const result = buildCronJobSubmitPayload({
      ...buildCronJob(),
      cronType: "weekly",
      cronTime: dayjs().hour(8).minute(30),
      cronDaysOfWeek: ["mon", "fri"],
      execution_model_key: "openai::gpt-5.4",
      notificationDelayValue: 2,
      notificationDelayUnit: "hours",
      request: {
        input: JSON.stringify([{ role: "user", content: [] }]),
      },
    });

    expect(result.schedule.cron).toBe("30 8 * * mon,fri");
    expect(result.model_slot).toEqual({
      provider_id: "openai",
      model: "gpt-5.4",
    });
    expect(result.meta?.notification_delay_minutes).toBe(120);
    expect(result.request?.input).toEqual([{ role: "user", content: [] }]);
  });

  it("normalizes manually entered skill ids before submit", () => {
    expect(normalizeSkillIdsInput("a, b\nc a")).toBe("a,b,c");
  });

  it("rejects invalid skill id characters", () => {
    expect(() => normalizeSkillIdsInput("bad/id")).toThrow();
  });

  it("rejects skill ids beyond the API length limit", () => {
    expect(() => normalizeSkillIdsInput("x".repeat(201))).toThrow();
  });

  it("maps form skillIds to API skill_ids in submit payload", () => {
    const result = buildCronJobSubmitPayload({
      ...buildCronJob(),
      skillIds: "a b",
    });

    expect(result.skill_ids).toBe("a,b");
  });

  it("hydrates API skill_ids into form skillIds when editing", () => {
    const result = buildCronJobFormValues(
      buildCronJob({
        skill_ids: "a,b",
      }),
    );

    expect(result.skillIds).toBe("a,b");
  });

  it("clears model_slot for text jobs on submit", () => {
    const result = buildCronJobSubmitPayload({
      ...buildCronJob({
        task_type: "text",
        text: "hello",
        request: undefined,
      }),
      cronType: "custom",
      cronCustom: "15 10 * * *",
      execution_model_key: "openai::gpt-5.4",
    });

    expect(result.task_type).toBe("text");
    expect(result.schedule.cron).toBe("15 10 * * *");
    expect(result.model_slot).toBeUndefined();
  });

  it("summarizes broadcast results with warning precedence", () => {
    expect(
      getBroadcastResultMessage([
        {
          tenant_id: "tenant-a",
          success: true,
          job_id: "job-1",
          cron: "0 9 * * *",
          timezone: "UTC",
          offset_minutes: 0,
          notification_timezone: "UTC",
          error: "",
          warning: "model_slot not copied",
        },
      ]),
    ).toEqual({
      tone: "warning",
      text: "Broadcasted 1 tenants, 1 with warnings",
    });
  });

  it("prefers failure summary over warning summary for mixed broadcast results", () => {
    expect(
      getBroadcastResultMessage([
        {
          tenant_id: "tenant-a",
          success: true,
          job_id: "job-1",
          cron: "0 9 * * *",
          timezone: "UTC",
          offset_minutes: 0,
          notification_timezone: "UTC",
          error: "",
          warning: "model_slot not copied",
        },
        {
          tenant_id: "tenant-b",
          success: false,
          job_id: "",
          cron: "0 9 * * *",
          timezone: "UTC",
          offset_minutes: 60,
          notification_timezone: "UTC",
          error: "boom",
          warning: "",
        },
      ]),
    ).toEqual({
      tone: "warning",
      text: "Broadcasted 1, failed 1",
    });
  });
});
