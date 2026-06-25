import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  clearAuthToken: vi.fn(),
  clearExternalToken: vi.fn(),
  ensureValidToken: vi.fn(),
  isExternalTokenEnabled: vi.fn(),
}));

vi.mock("./config", () => ({
  clearAuthToken: mocks.clearAuthToken,
  getApiUrl: (path: string) => path,
}));

vi.mock("./authHeaders", () => ({
  buildAuthHeaders: () => ({
    "X-Auth-Authorization": "Bearer refreshed-token",
  }),
}));

vi.mock("./externalToken", () => ({
  clearExternalToken: mocks.clearExternalToken,
  ensureValidToken: mocks.ensureValidToken,
  isExternalTokenEnabled: mocks.isExternalTokenEnabled,
}));

describe("request", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mocks.ensureValidToken.mockResolvedValue("refreshed-token");
    mocks.isExternalTokenEnabled.mockReturnValue(true);
    window.history.replaceState(null, "", "/");
  });

  it("外部 token 刷新后重试成功时不会跳登录兜底", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(
        Response.json({ ok: true }, { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const { request } = await import("./request");

    await expect(request("/api/test")).resolves.toEqual({ ok: true });
    expect(mocks.ensureValidToken).toHaveBeenCalledWith(true);
    expect(mocks.clearAuthToken).not.toHaveBeenCalled();
  });

  it("外部 token 重试返回非 401 时保留真实错误且不跳登录", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(
        Response.json({ detail: "权限不足" }, { status: 403 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const { request } = await import("./request");

    await expect(request("/api/test")).rejects.toThrow("权限不足");
    expect(mocks.clearAuthToken).not.toHaveBeenCalled();
    expect(mocks.clearExternalToken).not.toHaveBeenCalled();
  });

  it("外部 token 刷新失败时只抛认证错误且不跳登录", async () => {
    mocks.ensureValidToken.mockRejectedValue(new Error("refresh failed"));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );

    const { request } = await import("./request");

    await expect(request("/api/test")).rejects.toThrow("登录状态已失效");
    expect(window.location.pathname).toBe("/");
    expect(mocks.clearExternalToken).toHaveBeenCalled();
    expect(mocks.clearAuthToken).not.toHaveBeenCalled();
  });

  it("外部 token 重试仍返回 401 时不跳登录", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const { request } = await import("./request");

    await expect(request("/api/test")).rejects.toThrow("登录状态已失效");
    expect(window.location.pathname).toBe("/");
    expect(mocks.clearExternalToken).toHaveBeenCalled();
    expect(mocks.clearAuthToken).not.toHaveBeenCalled();
  });

  it("普通 token 模式 401 时只清理本地 token 且不跳登录", async () => {
    mocks.isExternalTokenEnabled.mockReturnValue(false);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );

    const { request } = await import("./request");

    await expect(request("/api/test")).rejects.toThrow("认证已失效");
    expect(window.location.pathname).toBe("/");
    expect(mocks.clearAuthToken).toHaveBeenCalled();
    expect(mocks.clearExternalToken).not.toHaveBeenCalled();
  });

  it("外部 token 重试时保留 FormData 的 Content-Type 处理", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(
        Response.json({ ok: true }, { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const formData = new FormData();
    formData.append("file", "content");
    const { request } = await import("./request");

    await request("/api/upload", { method: "POST", body: formData });

    const retryInit = fetchMock.mock.calls[1][1] as RequestInit;
    const retryHeaders = retryInit.headers as Headers;
    expect(retryHeaders.has("Content-Type")).toBe(false);
  });

  it("sets JSON Content-Type for DELETE requests with a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({ ok: true }, { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { request } = await import("./request");

    await request("/api/archive/items", {
      method: "DELETE",
      body: JSON.stringify({ archive_item_ids: ["archive-1"] }),
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});
