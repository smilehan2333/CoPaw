import { beforeEach, describe, expect, it, vi } from "vitest";
import { providerApi } from "./provider";
import { request } from "../request";

const storeMocks = vi.hoisted(() => ({
  invalidate: vi.fn(),
  setActiveModels: vi.fn(),
}));

vi.mock("../request", () => ({
  request: vi.fn(),
}));

vi.mock("../../stores/providerModelStore", () => ({
  useProviderModelStore: {
    getState: () => ({
      invalidate: storeMocks.invalidate,
      setActiveModels: storeMocks.setActiveModels,
    }),
  },
}));

describe("providerApi cache integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("updates shared active model state after setting the active llm", async () => {
    const activeModels = {
      active_llm: { provider_id: "openai", model: "gpt-4" },
    };
    vi.mocked(request).mockResolvedValue(activeModels);

    await expect(
      providerApi.setActiveLlm({
        provider_id: "openai",
        model: "gpt-4",
        scope: "global",
      }),
    ).resolves.toEqual(activeModels);

    expect(storeMocks.setActiveModels).toHaveBeenCalledWith(activeModels);
    expect(storeMocks.invalidate).not.toHaveBeenCalled();
  });

  it("invalidates shared provider data after provider configuration changes", async () => {
    vi.mocked(request).mockResolvedValue({ id: "openai" });

    await providerApi.configureProvider("openai", { api_key: "new-key" });

    expect(storeMocks.invalidate).toHaveBeenCalledWith({
      providers: true,
      active: false,
    });
  });
});
