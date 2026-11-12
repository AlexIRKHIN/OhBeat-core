import { describe, expect, it } from "vitest";

import { EMPTY_AUDIT_FILTERS, actionGroups, auditParams } from "./admin";

describe("FR-35 Audit Log filters (GAP-75)", () => {
  it("groups actions by the part before the dot", () => {
    expect(actionGroups(["payment.created", "payment.succeeded", "order.created", "contract.signed"])).toEqual([
      "contract.",
      "order.",
      "payment.",
    ]);
  });

  it("sends only filled filters and the cursor", () => {
    const params = auditParams({ ...EMPTY_AUDIT_FILTERS, action: "payment.", from: "2026-11-01" }, "abc");
    expect(params.toString()).toBe("action=payment.&from=2026-11-01&cursor=abc");
  });
});
