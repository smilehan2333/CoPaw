import type { CronJobSpecOutput } from "@/api/types";
import { buildCronJobSubmitPayload } from "../Control/CronJobs/helpers";

export type CronTaskEditFormValues = Parameters<
  typeof buildCronJobSubmitPayload
>[0];

export type ReplaceCronJob = (
  jobId: string,
  payload: ReturnType<typeof buildCronJobSubmitPayload>,
) => Promise<unknown>;

export async function submitCronTaskEdit(
  task: CronJobSpecOutput,
  values: CronTaskEditFormValues,
  replaceCronJob: ReplaceCronJob,
) {
  const payload = buildCronJobSubmitPayload(values);
  await replaceCronJob(task.id, payload);
  return payload;
}
