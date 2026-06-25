import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Modal, message, Tooltip, Spin } from "antd";
import { FullscreenOutlined } from "@ant-design/icons";
import {
  SparkFalseLine,
  SparkDownloadLine,
  // SparkCopyLine,
  // SparkTrueLine,
} from "@agentscope-ai/icons";
import { IconButton } from "@agentscope-ai/design";
import {
  getFileIcon,
  getFileType,
  getContentType,
  isDynamicRenderHtmlLink,
  extractResultIdFromUrl,
  extractTemplateIdFromUrl,
} from "./fileUtils";
import Markdown from "../Markdown";
import { htmlPreviewEventsApi } from "@/api/modules/htmlPreviewEvents";
import { useHtmlPreviewTracking } from "../HtmlPreviewTrackingContext";
import { useDynamicRender } from "../DynamicRenderContext";
import {
  attachHtmlPreviewClickTracker,
  type NestedHtmlPreviewRequest,
} from "./htmlPreviewClickTracking";
import { dynamicRenderApi } from "@/api/modules/dynamicRender";

export interface FilePreviewModalProps {
  open: boolean;
  onClose: () => void;
  fileUrl: string;
  fileName: string;
  enableClickTracking?: boolean;
  enableListSnapshotTracking?: boolean;
  trackingListKey?: string | null;
  trackingListName?: string | null;
  defaultCustomerInfo?: Record<string, string> | null;
}

// 使用div渲染的模名称列表
const divRenderableFiles = ["html_template_deposit_v3.html"];

function FilePreviewModal(props: FilePreviewModalProps) {
  const {
    open,
    onClose,
    fileUrl,
    fileName,
    enableClickTracking = false,
    enableListSnapshotTracking = true,
    trackingListKey,
    trackingListName,
    defaultCustomerInfo,
  } = props;
  const [copied, setCopied] = useState(false);
  const [fullscreen, setFullscreen] = useState(true);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [markdownContent, setMarkdownContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nestedPreview, setNestedPreview] =
    useState<NestedHtmlPreviewRequest | null>(null);
  const [dynamicRenderLoading, setDynamicRenderLoading] = useState(false);
  const [isFileGenerating, setIsFileGenerating] = useState(false);
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);
  // 存储动态渲染的 HTML 内容（直接渲染到 div 时使用）
  const [renderedHtmlContent, setRenderedHtmlContent] = useState<string | null>(
    null
  );
  // 缓存动态渲染API返回的原始数据，避免重复请求
  const [dynamicRenderCache, setDynamicRenderCache] = useState<Record<string, unknown> | null>(null);
  // 用于直接渲染 HTML 的 ref
  const contentDivRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const cleanupClickTrackingRef = useRef<(() => void) | null>(null);
  const cleanupCaptureClickRef = useRef<(() => void) | null>(null);
  const trackingContext = useHtmlPreviewTracking();
  const { renderTemplate, templateList } = useDynamicRender();
  const fileType = useMemo(() => getFileType(fileName), [fileName]);
  const isMarkdownFile = useMemo(() => /\.mdx?$/i.test(fileName), [fileName]);
  const { icon, color } = useMemo(() => getFileIcon(fileName, 48), [fileName]);
  const isHtmlPreview = useMemo(
    () =>
      fileType === "previewable" && getContentType(fileName) === "text/html",
    [fileName, fileType]
  );
  // 判断是否为动态渲染类型
  const isDynamicRender = useMemo(
    () => isDynamicRenderHtmlLink(fileUrl),
    [fileUrl]
  );

  // 获取动态渲染数据的函数（带轮询逻辑）
  const fetchDynamicRenderData = useCallback(
    async (resultId: string, templateId: string) => {
      try {
        const res = await dynamicRenderApi.getRecordData(resultId, templateId);
        // 如果返回码不是 200，说明文件正在生成中
        if (res.code !== "200") {
          setIsFileGenerating(true);
          setDynamicRenderLoading(true);
          setLoading(true);
          // 清除之前的错误
          setError(null);
          // 设置定时器，每10秒再次查询
          if (pollingTimerRef.current) {
            clearTimeout(pollingTimerRef.current);
          }
          pollingTimerRef.current = setTimeout(() => {
            fetchDynamicRenderData(resultId, templateId);
          }, 10000);
          return;
        }
        // 成功获取数据，停止轮询
        setIsFileGenerating(false);
        if (pollingTimerRef.current) {
          clearTimeout(pollingTimerRef.current);
          pollingTimerRef.current = null;
        }
        // 缓存数据供下载使用
        setDynamicRenderCache(res.data as Record<string, unknown>);
        const templateIdNum = parseInt(templateId, 10);
        const renderedHtml = await renderTemplate(templateIdNum, res.data);
        if (renderedHtml) {
          // 通过templateList 获取模板名称
          const templateName = templateList.find(
            (t) => t.templateId === templateIdNum
          )?.t;
          if (divRenderableFiles.includes(templateName)) {
            setRenderedHtmlContent(renderedHtml);
          } else {
            const blob = new Blob([renderedHtml], { type: "text/html" });
            const url = URL.createObjectURL(blob);
            setBlobUrl(url);
          }
        } else {
          setError("模板渲染失败");
        }
      } catch (err) {
        console.error("获取数据失败:", err);
        setError("数据加载失败");
        setIsFileGenerating(false);
      } finally {
        setLoading(false);
        setDynamicRenderLoading(false);
      }
    },
    [renderTemplate]
  );

  // fetch 文件数据并创建 Blob URL 或动态渲染
  useEffect(() => {
    if (open && fileType === "previewable" && fileUrl) {
      setLoading(true);
      setError(null);
      setBlobUrl(null);
      setMarkdownContent(null);
      setIsFileGenerating(false);

      // 清理之前的轮询定时器
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }

      // 动态渲染逻辑
      if (isDynamicRender) {
        setDynamicRenderLoading(true);
        const resultId = extractResultIdFromUrl(fileUrl);
        const templateId = extractTemplateIdFromUrl(fileUrl);

        if (!resultId || !templateId) {
          setError("缺少必要的参数");
          setLoading(false);
          setDynamicRenderLoading(false);
          return;
        }
        fetchDynamicRenderData(resultId, templateId);

        return;
      }

      // 原有逻辑：直接加载文件
      fetch(fileUrl)
        .then(async (res) => {
          if (!res.ok) throw new Error("加载失败");

          if (isMarkdownFile) {
            setMarkdownContent(await res.text());
            return;
          }

          const blob = await res.blob();
          const contentType = getContentType(fileName);
          const newBlob = new Blob([blob], { type: contentType });
          const url = URL.createObjectURL(newBlob);
          setBlobUrl(url);
        })
        .catch(() => {
          setError("文件暂时无法预览");
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [
    open,
    fileType,
    fileUrl,
    fileName,
    isMarkdownFile,
    isDynamicRender,
    renderTemplate,
    fetchDynamicRenderData,
  ]);

  // 清理 Blob URL
  useEffect(() => {
    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [blobUrl]);

  // 清理动态渲染的 HTML 内容
  useEffect(() => {
    return () => {
      setRenderedHtmlContent(null);
    };
  }, []);

  // 处理捕获阶段的动态渲染链接点击事件
  useEffect(() => {
    const contentDiv = contentDivRef.current;
    if (!contentDiv || !renderedHtmlContent) {
      return;
    }

    // 在捕获阶段处理点击事件
    const handleCaptureClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const anchorElement = target.closest("a[data-preview-modal='true']");

      if (
        anchorElement &&
        anchorElement instanceof HTMLAnchorElement &&
        anchorElement.getAttribute("href")
      ) {
        // 使用 getAttribute 获取原始href，避免浏览器自动URL编码
        const href = anchorElement.getAttribute("href") as string;
        const resultId = extractResultIdFromUrl(href);
        const templateId = extractTemplateIdFromUrl(href);
        // 如果 href 包含 resultId 和 templateId，则阻止默认行为，进入嵌套预览
        if (resultId && templateId) {
          event.preventDefault();
          event.stopPropagation();

          // 提取文件名
          const fileName = href.split("?")[0]?.split('/').pop() || 'preview.html';

          // 设置嵌套预览
          setNestedPreview({
            fileUrl: href,
            fileName,
            listKey: fileUrl,
            listName: fileName,
            customerInfo: defaultCustomerInfo || null,
          });
        }
      }
    };

    // 使用捕获阶段的事件监听
    contentDiv.addEventListener("click", handleCaptureClick, true);

    // 清理函数
    cleanupCaptureClickRef.current = () => {
      contentDiv.removeEventListener("click", handleCaptureClick, true);
    };

    return () => {
      cleanupCaptureClickRef.current?.();
      cleanupCaptureClickRef.current = null;
    };
  }, [renderedHtmlContent, fileUrl, defaultCustomerInfo]);

  useEffect(() => {
    if (!open) {
      cleanupClickTrackingRef.current?.();
      cleanupClickTrackingRef.current = null;
      cleanupCaptureClickRef.current?.();
      cleanupCaptureClickRef.current = null;
      setNestedPreview(null);
      setRenderedHtmlContent(null);
      setDynamicRenderCache(null);
      setIsFileGenerating(false);
      // 清理轮询定时器
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    }
  }, [open]);

  useEffect(() => {
    return () => {
      cleanupClickTrackingRef.current?.();
      cleanupClickTrackingRef.current = null;
      cleanupCaptureClickRef.current?.();
      cleanupCaptureClickRef.current = null;
      // 清理轮询定时器
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    };
  }, []);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(fileUrl);
      message.success("链接已复制");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      message.error("复制失败");
    }
  }, [fileUrl]);

  const handleDownload = useCallback(async () => {
    // 动态渲染类型的特殊下载逻辑
    if (isDynamicRender) {
      try {
        const resultId = extractResultIdFromUrl(fileUrl);
        const templateId = extractTemplateIdFromUrl(fileUrl);

        if (!resultId || !templateId) {
          console.error("动态渲染链接缺少必要的参数");
          return;
        }

        // 优先使用缓存数据，避免重复请求接口
        const renderData = dynamicRenderCache || (await dynamicRenderApi.getRecordData(resultId, templateId)).data;
        const templateIdNum = parseInt(templateId, 10);
        const renderedHtml = await renderTemplate(templateIdNum, renderData);

        if (renderedHtml) {
          // 将HTML内容转换为Blob进行下载
          const blob = new Blob([renderedHtml], { type: "text/html" });
          const blobUrl = URL.createObjectURL(blob);

          const link = document.createElement("a");
          link.href = blobUrl;
          link.download = fileName.endsWith(".html")
            ? fileName
            : `${fileName}.html`;
          link.target = "_blank";
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);

          // 清理Blob URL
          setTimeout(() => URL.revokeObjectURL(blobUrl), 100);
        } else {
          console.error("模板渲染失败");
        }
      } catch (error) {
        console.error("动态渲染下载失败:", error);
      }
    } else {
      // 普通文件的下载逻辑
      const link = document.createElement("a");
      link.href = fileUrl;
      link.download = fileName;
      link.target = "_blank";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  }, [fileUrl, fileName, isDynamicRender, renderTemplate, dynamicRenderCache]);

  const handleFullscreen = useCallback(() => {
    setFullscreen((prev) => !prev);
  }, []);

  const handleIframeLoad = useCallback(() => {
    cleanupClickTrackingRef.current?.();
    cleanupClickTrackingRef.current = null;

    const iframe = iframeRef.current;
    if (!iframe || !isHtmlPreview || !enableClickTracking) {
      return;
    }

    try {
      cleanupClickTrackingRef.current = attachHtmlPreviewClickTracker({
        iframe,
        metadata: {
          cronTaskId: trackingContext.cronTaskId,
          cronTaskName: trackingContext.cronTaskName,
          fileUrl,
          fileName,
          listKey: trackingListKey,
          listName: trackingListName,
          defaultCustomerInfo,
        },
        reporter: htmlPreviewEventsApi.recordClick,
        listSnapshotReporter: enableListSnapshotTracking
          ? htmlPreviewEventsApi.recordListSnapshot
          : undefined,
        onOpenNestedPreview: setNestedPreview,
      });
    } catch (error) {
      console.warn("Failed to attach HTML preview click tracker:", error);
    }
  }, [
    enableClickTracking,
    fileName,
    fileUrl,
    isHtmlPreview,
    enableListSnapshotTracking,
    defaultCustomerInfo,
    trackingListKey,
    trackingListName,
    trackingContext,
  ]);

  const previewHeight = fullscreen ? "85vh" : "500px";

  const renderPreviewContent = useMemo(() => {
    if (fileType === "previewable") {
      if (loading || isFileGenerating) {
        const tip = isFileGenerating
          ? "文件正在生成中，内容准备完成后，页面会自动展示最新预览"
          : dynamicRenderLoading
            ? "正在渲染报告..."
            : "加载中...";
        return <Spin tip={tip} />;
      }
      if (error) {
        return (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              padding: "24px",
            }}
          >
            <div
              style={{
                color: "#8c8c8c",
                marginBottom: "16px",
                fontSize: "14px",
              }}
            >
              {error}
            </div>
            <IconButton icon={<SparkDownloadLine />} onClick={handleDownload}>
              下载文件查看
            </IconButton>
          </div>
        );
      }
      if (isMarkdownFile && markdownContent !== null) {
        return (
          <div
            style={{
              width: "100%",
              height: previewHeight,
              overflow: "auto",
              padding: "16px",
              boxSizing: "border-box",
              textAlign: "left",
            }}
          >
            <Markdown content={markdownContent} />
          </div>
        );
      }
      if (renderedHtmlContent) {
        // 动态渲染的 HTML 直接渲染到 div，点击事件可以直接监听
        return (
          <div
            ref={contentDivRef}
            style={{ width: "100%", height: previewHeight, overflow: "auto" }}
            dangerouslySetInnerHTML={{ __html: renderedHtmlContent }}
          />
        );
      }
      if (blobUrl) {
        return (
          <div style={{ width: "100%", height: previewHeight }}>
            <iframe
              ref={iframeRef}
              src={blobUrl}
              style={{ width: "100%", height: "100%", border: "none" }}
              title="File Preview"
              onLoad={handleIframeLoad}
            />
          </div>
        );
      }
      return null;
    }

    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "24px",
          textAlign: "center",
        }}
      >
        <div style={{ marginBottom: "16px", color }}>{icon}</div>
        <div
          style={{
            fontSize: "16px",
            fontWeight: 500,
            marginBottom: "8px",
            maxWidth: "300px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {fileName}
        </div>
        <div
          style={{ fontSize: "12px", color: "#8c8c8c", marginBottom: "16px" }}
        >
          该文件类型不支持预览
        </div>
        <IconButton icon={<SparkDownloadLine />} onClick={handleDownload}>
          下载文件
        </IconButton>
      </div>
    );
  }, [
    fileType,
    loading,
    error,
    isMarkdownFile,
    markdownContent,
    previewHeight,
    blobUrl,
    renderedHtmlContent,
    fileName,
    icon,
    color,
    handleDownload,
    handleIframeLoad,
  ]);

  const headerActions = useMemo(() => {
    const actions = [
      // <Tooltip key="copy" title="复制链接">
      //   <IconButton
      //     size="small"
      //     icon={copied ? <SparkTrueLine style={{ color: "#52c41a" }} /> : <SparkCopyLine />}
      //     onClick={handleCopy}
      //     bordered={false}
      //   />
      // </Tooltip>,
      <Tooltip key="download" title="下载文件">
        <IconButton
          size="small"
          icon={<SparkDownloadLine />}
          onClick={handleDownload}
          bordered={false}
        />
      </Tooltip>,
    ];

    if (fileType === "previewable") {
      actions.unshift(
        <Tooltip key="fullscreen" title={fullscreen ? "退出全屏" : "全屏预览"}>
          <IconButton
            size="small"
            icon={<FullscreenOutlined />}
            onClick={handleFullscreen}
            bordered={false}
          />
        </Tooltip>
      );
    }

    return actions;
  }, [
    fileType,
    handleCopy,
    handleDownload,
    handleFullscreen,
    copied,
    fullscreen,
  ]);

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={fullscreen ? "95vw" : 800}
        centered
        closeIcon={
          <IconButton size="small" icon={<SparkFalseLine />} bordered={false} />
        }
        title={
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              width: "100%",
            }}
          >
            <span
              style={{
                fontSize: "14px",
                fontWeight: 500,
                maxWidth: fullscreen ? "60vw" : "400px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {fileName}
            </span>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
                marginRight: "32px",
              }}
            >
              {headerActions}
            </div>
          </div>
        }
        styles={{
          content: { padding: "16px 24px" },
          body: { padding: "16px 0" },
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: fullscreen ? "85vh" : "200px",
          }}
        >
          {renderPreviewContent}
        </div>
      </Modal>
      {nestedPreview && (
        <FilePreviewModal
          open
          onClose={() => setNestedPreview(null)}
          fileUrl={nestedPreview.fileUrl}
          fileName={nestedPreview.fileName}
          enableClickTracking
          enableListSnapshotTracking={false}
          trackingListKey={nestedPreview.listKey}
          trackingListName={nestedPreview.listName}
          defaultCustomerInfo={nestedPreview.customerInfo}
        />
      )}
    </>
  );
}

export default FilePreviewModal;