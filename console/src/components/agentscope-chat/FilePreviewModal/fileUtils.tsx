import React from "react";
import {
  xlsxIcon,
  imgIcon,
  mdIcon,
  pdfIcon,
  pptIcon,
  docIcon,
  zipIcon,
  videoIcon,
  audioIcon,
} from "@/assets/icons";

// 浏览器可预览的文件类型
export const BROWSER_PREVIEWABLE_EXTS = [
  // 图片
  "png", "jpg", "jpeg", "gif", "bmp", "webp", "svg",
  // 视频（浏览器原生支持）
  "mp4", "webm",
  // 音频（浏览器原生支持）
  "mp3", "wav", "ogg",
  // PDF（浏览器内置预览器）
  "pdf",
  // HTML
  "html", "htm",
  // 文本
  "txt",
  // Markdown（显示源码）
  "md", "mdx", "json",
];

// Content-Type 映射
const CONTENT_TYPE_MAP: Record<string, string> = {
  // 图片
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  bmp: "image/bmp",
  webp: "image/webp",
  svg: "image/svg+xml",
  // 视频
  mp4: "video/mp4",
  webm: "video/webm",
  // 音频
  mp3: "audio/mpeg",
  wav: "audio/wav",
  ogg: "audio/ogg",
  // PDF
  pdf: "application/pdf",
  // HTML
  html: "text/html",
  htm: "text/html",
  // 文本
  txt: "text/plain",
  md: "text/plain",
  mdx: "text/plain",
  json: "text/plain",
};

const DEFAULT_ICON_COLOR = "#8c8c8c";

export function safeDecodeFileName(fileName: string): string {
  try {
    return decodeURIComponent(fileName);
  } catch {
    return fileName;
  }
}

export function extractDecodedFileNameFromUrl(url: string, fallback: string): string {
  try {
    const urlObj = new URL(url, window.location.origin);
    const fileName = urlObj.pathname.split("/").pop();
    return fileName ? safeDecodeFileName(fileName) : fallback;
  } catch {
    return fallback;
  }
}

const IconImage = ({ url, size = 24 }: { url: string; size?: number }) => (
  <img src={url} width={size} height={size} alt="file icon" style={{ objectFit: "contain" }} />
);

// File icon mapping for card display (smaller icons)
const PRESET_FILE_ICONS: {
  ext: string[];
  color: string;
  icon: React.ReactElement;
}[] = [
  { icon: <IconImage url={xlsxIcon} />, color: "#22b35e", ext: ["xlsx", "xls"] },
  { icon: <IconImage url={imgIcon} />, color: DEFAULT_ICON_COLOR, ext: ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"] },
  { icon: <IconImage url={mdIcon} />, color: DEFAULT_ICON_COLOR, ext: ["md", "mdx"] },
  { icon: <IconImage url={pdfIcon} />, color: "#ff4d4f", ext: ["pdf"] },
  { icon: <IconImage url={pptIcon} />, color: "#ff6e31", ext: ["ppt", "pptx"] },
  { icon: <IconImage url={docIcon} />, color: "#1677ff", ext: ["doc", "docx"] },
  { icon: <IconImage url={zipIcon} />, color: "#fab714", ext: ["zip", "rar", "7z", "tar", "gz"] },
  { icon: <IconImage url={videoIcon} />, color: "#ff4d4f", ext: ["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"] },
  { icon: <IconImage url={audioIcon} />, color: "#8c8c8c", ext: ["mp3", "wav", "flac", "ape", "aac", "ogg", "m4a"] },
];

function getExtension(fileName: string): string {
  const parts = fileName.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function matchExt(suffix: string, ext: string[]): boolean {
  const lowerSuffix = `.${suffix}`;
  return ext.some((e) => lowerSuffix.toLowerCase() === `.${e}`);
}

export type FileType = "previewable" | "unsupported";

const AUTO_PREVIEW_MARKERS = [
  "[auto-preview]",
  "auto-preview",
  "存款到期完整客户名单",
];
const HTML_PREVIEW_EXTS = ["html", "htm"];

function safeDecodeValue(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function extractUrlFileName(url: string): string {
  try {
    const urlObj = new URL(url, window.location.origin);
    return urlObj.pathname.split("/").pop() || "";
  } catch {
    return url.split(/[?#]/)[0].split("/").pop() || "";
  }
}

function includesAutoPreviewMarker(value: string): boolean {
  const decodedValue = safeDecodeValue(value);
  return AUTO_PREVIEW_MARKERS.some((marker) => decodedValue.includes(marker));
}

function hasHtmlExtension(fileName: string): boolean {
  const ext = getExtension(safeDecodeValue(fileName));
  return matchExt(ext, HTML_PREVIEW_EXTS);
}

export function isAutoPreviewHtmlLink(url: string, fileName?: string): boolean {
  const extractedFileName = extractUrlFileName(url);
  const candidates = [url, extractedFileName, fileName || ""];

  return (
    hasHtmlExtension(fileName || extractedFileName) &&
    candidates.some((candidate) => includesAutoPreviewMarker(candidate))
  );
}

export function getFileType(fileName: string): FileType {
  const ext = getExtension(fileName);
  if (matchExt(ext, BROWSER_PREVIEWABLE_EXTS)) return "previewable";
  return "unsupported";
}

export function getContentType(fileName: string): string {
  const ext = getExtension(fileName);
  return CONTENT_TYPE_MAP[ext] || "application/octet-stream";
}

export function getFileIcon(fileName: string, size = 24): { icon: React.ReactElement; color: string } {
  const ext = getExtension(fileName);

  for (const { ext: extensions, color } of PRESET_FILE_ICONS) {
    if (matchExt(ext, extensions)) {
      const iconUrl = getIconUrlByExt(extensions[0]);
      return { icon: <IconImage url={iconUrl} size={size} />, color };
    }
  }

  return {
    icon: <IconImage url={zipIcon} size={size} />,
    color: DEFAULT_ICON_COLOR,
  };
}

function getIconUrlByExt(ext: string): string {
  const extToIcon: Record<string, string> = {
    xlsx: xlsxIcon, xls: xlsxIcon,
    png: imgIcon, jpg: imgIcon, jpeg: imgIcon, gif: imgIcon, bmp: imgIcon, webp: imgIcon, svg: imgIcon,
    md: mdIcon, mdx: mdIcon,
    pdf: pdfIcon,
    ppt: pptIcon, pptx: pptIcon,
    doc: docIcon, docx: docIcon,
    zip: zipIcon, rar: zipIcon, "7z": zipIcon, tar: zipIcon, gz: zipIcon,
    mp4: videoIcon, avi: videoIcon, mov: videoIcon, wmv: videoIcon, flv: videoIcon, mkv: videoIcon, webm: videoIcon,
    mp3: audioIcon, wav: audioIcon, flac: audioIcon, ape: audioIcon, aac: audioIcon, ogg: audioIcon, m4a: audioIcon,
    txt: mdIcon, json: mdIcon, xml: mdIcon, csv: mdIcon, log: mdIcon,
    yaml: mdIcon, yml: mdIcon, toml: mdIcon, ini: mdIcon, conf: mdIcon, config: mdIcon, env: mdIcon,
    sh: mdIcon, bash: mdIcon, zsh: mdIcon, ps1: mdIcon, bat: mdIcon, cmd: mdIcon,
    html: mdIcon, htm: mdIcon, xhtml: mdIcon,
  };
  return extToIcon[ext] || zipIcon;
}

/**
 * 从 URL 中提取 resultId 参数
 */
export function extractResultIdFromUrl(url: string): string | null {
  try {
    const urlObj = new URL(url, window.location.origin);
    const resultId = urlObj.searchParams.get("resultId");
    return resultId;
  } catch {
    return null;
  }
}

/**
 * 从 URL 中提取 templateId 参数
 */
export function extractTemplateIdFromUrl(url: string): string | null {
  try {
    const urlObj = new URL(url, window.location.origin);
    const templateId = urlObj.searchParams.get("templateId");
    return templateId;
  } catch {
    return null;
  }
}

/**
 * 判断是否为动态渲染类型的 HTML 链接
 * 条件：URL 包含 resultId 和 templateId 参数
 */
export function isDynamicRenderHtmlLink(url: string): boolean {
  const resultId = extractResultIdFromUrl(url);
  const templateId = extractTemplateIdFromUrl(url);
  return !!(resultId && templateId);
}