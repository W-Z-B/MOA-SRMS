import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../../api/types";
import { AdmissionsScreen } from "./AdmissionsScreen";

const { get, post, patch } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  get,
  post,
  patch,
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const ME: Me = {
  id: 1,
  username: "registrar",
  name: "Registrar",
  roles: ["registrar"],
  is_superuser: false,
  mfa_required: false,
  mfa_verified: true,
  employee_no: null,
  student_id: null,
  student_no: null,
};

const PROGRAMMES = { count: 1, next: null, previous: null, results: [{ id: 1, code: "DIP-AGR", name: "Diploma in Agriculture", award: "diploma", campus_codes: ["MRP"] }] };

const APPLICATION = {
  id: 7,
  reference: "APP-2026-0007",
  full_name: "Devi Ramnarine",
  programme: 1,
  campus_code: "MRP",
  intake_year: 2026,
  state: "assessed",
  assessment_score: "78.50",
  assessment_notes: "",
  decision_comment: "",
  allowed_actions: ["offer", "reject", "withdraw"],
  student_no: null,
  waitlist_rank: null,
  document_count: 0,
  capacity_remaining: 1,
};

function mockApplications(results = [APPLICATION]) {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/applications/")) return Promise.resolve({ count: results.length, next: null, previous: null, results });
    if (path.startsWith("/programmes/")) return Promise.resolve(PROGRAMMES);
    if (path.startsWith("/application-documents/")) return Promise.resolve({ count: 0, next: null, previous: null, results: [] });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  post.mockResolvedValue({});
  patch.mockResolvedValue({});
});

describe("AdmissionsScreen", () => {
  it("lists applications with their state and programme code", async () => {
    mockApplications();
    render(<AdmissionsScreen me={ME} campusCode={null} />);

    expect(await screen.findByText("APP-2026-0007")).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Devi Ramnarine")).toBeInTheDocument();
    expect(table.getByText("DIP-AGR")).toBeInTheDocument();
    expect(table.getByText("Assessed")).toBeInTheDocument();
  });

  it("opens the review file and shows only the actions the API allowed", async () => {
    mockApplications();
    const user = userEvent.setup();
    render(<AdmissionsScreen me={ME} campusCode={null} />);

    await user.click(await screen.findByText("APP-2026-0007"));

    const file = screen.getByRole("heading", { name: "Devi Ramnarine" }).closest("aside") as HTMLElement;
    expect(within(file).getByRole("button", { name: "Make offer" })).toBeInTheDocument();
    expect(within(file).getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(within(file).queryByRole("button", { name: "Mark as assessed" })).not.toBeInTheDocument();
    expect(within(file).getByText(/1 places left/)).toBeInTheDocument();
  });

  it("requires a comment before rejecting", async () => {
    mockApplications();
    const user = userEvent.setup();
    render(<AdmissionsScreen me={ME} campusCode={null} />);

    await user.click(await screen.findByText("APP-2026-0007"));
    await user.type(screen.getByLabelText("Decision comment"), "Entry requirements not met");
    await user.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/applications/7/transition/", {
        action: "reject",
        comment: "Entry requirements not met",
      }),
    );
  });

  it("saves an assessment score through a PATCH", async () => {
    mockApplications();
    const user = userEvent.setup();
    render(<AdmissionsScreen me={ME} campusCode={null} />);

    await user.click(await screen.findByText("APP-2026-0007"));
    const score = screen.getByLabelText("Assessment score");
    await user.clear(score);
    await user.type(score, "85");
    await user.click(screen.getByRole("button", { name: "Save score" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith("/applications/7/", { assessment_score: "85" }));
  });
});
