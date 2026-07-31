// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  apiCall: vi.fn(),
  apiClient: {},
}));

import { apiCall } from "@/api/client";
import {
  fetchFreezoneImageModels,
  fetchFreezoneVideoModels,
} from "@/api/ops";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dreamina media model provider normalization", () => {
  it("preserves Dreamina provider metadata for image models", async () => {
    vi.mocked(apiCall).mockResolvedValue([
      {
        id: "dreamina_subscription",
        provider: "dreamina",
        apiModel: "dreamina_subscription",
        label: "Dreamina Seedream 5.0",
      },
    ]);

    const models = await fetchFreezoneImageModels("demo");

    expect(models[0]?.providerId).toBe("dreamina");
  });

  it("infers Dreamina rather than Seedance for raw video model ids", async () => {
    vi.mocked(apiCall).mockResolvedValue(["dreamina_seedance2.0fast"]);

    const models = await fetchFreezoneVideoModels("demo");

    expect(models[0]?.providerId).toBe("dreamina");
  });
});
