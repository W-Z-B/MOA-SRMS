import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardScreen } from "./DashboardScreen";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  get,
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const FUNNEL = {
  key: "enrolment-funnel",
  name: "",
  rows: [
    { programme: "DIP-AGR", name: "Diploma in Agriculture", intake_year: 2026, applied: 10, admitted: 8, enrolled: 6, retained: 5, graduated: 2 },
  ],
};

const RETENTION = {
  key: "retention-by-cohort",
  name: "",
  rows: [
    { programme: "DIP-AGR", name: "Diploma in Agriculture", intake_year: 2026, total: 6, withdrawn: 1, dismissed: 0, graduated: 2, active: 3, retained: 5, attrition_rate: 16.7 },
  ],
};

const FEES = {
  key: "fee-collection-status",
  name: "",
  rows: [
    { term: "2026-27-S1", charged: "50000.00", collected: "20000.00", outstanding: "30000.00", collection_rate: 40.0 },
    { term: "unallocated", charged: "0", collected: "5000.00", outstanding: "0", collection_rate: null },
  ],
};

describe("DashboardScreen", () => {
  it("renders the three real dashboards (S-D01, S-D02, S-D06) from their reports", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/reports/enrolment-funnel/") return Promise.resolve(FUNNEL);
      if (path === "/reports/retention-by-cohort/") return Promise.resolve(RETENTION);
      if (path === "/reports/fee-collection-status/") return Promise.resolve(FEES);
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });

    render(<DashboardScreen />);

    expect(await screen.findByRole("img", { name: "Enrolment funnel" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Retention and attrition by cohort" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Fee collection status by term" })).toBeInTheDocument();

    // Headline tiles computed from the report rows, not hard-coded. "10" (applied) also appears
    // as a value label inside the funnel chart's own SVG, so at least one match is enough.
    expect(screen.getAllByText("10").length).toBeGreaterThan(0);
    expect(screen.getByText("20%")).toBeInTheDocument(); // 2 graduated / 10 applied
    expect(screen.getByText("G$20,000")).toBeInTheDocument(); // collected
    expect(screen.getByText(/5,000 in payments fell outside/)).toBeInTheDocument();
  });
});
