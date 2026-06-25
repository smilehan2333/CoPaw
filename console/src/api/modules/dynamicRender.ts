import { request } from "../request";

export interface TemplateInfo {
  templateName: string;
  templateId: number;
}

export interface TemplateListResponse {
  data: TemplateInfo[];
}

export interface TemplateContentResponse {
  file_name: string;
  content: string;
}

export interface RecordDataRequest {
  resultId: string;
  templateId: string;
}

// Dynamic Render API
export const dynamicRenderApi = {
  getTemplateList: () =>
    request<TemplateListResponse>("/template/file-templates", {
      method: "GET",
    }),

  getTemplateContent: (fileName: string) =>
    request<TemplateContentResponse>(
      `/assets/text/read?file_name=${fileName}`,
      {
        method: "GET",
      },
    ),

  getRecordData: (resultId: string, templateId: string) =>
    request<Record<string, unknown>>("/template/result", {
      method: "POST",
      body: JSON.stringify({
        resultId,
        templateId: parseInt(templateId),
      }),
    }),
};