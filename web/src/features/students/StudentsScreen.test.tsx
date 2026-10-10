import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../../api/types";
import { StudentsScreen } from "./StudentsScreen";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  get,
  post,
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

const STUDENT = {
  id: 9,
  student_no: "26MRP0001",
  full_name: "Ravi Singh",
  date_of_birth: "2006-04-02",
  gender: "M",
  national_id_masked: "•••321",
  email: "",
  phone: "",
  region: "",
  campus_code: "MRP",
  programme: 1,
  programme_code: "DIP-AGR",
  programme_name: "Diploma in Agriculture",
  intake_year: 2026,
  status: "enrolled",
  is_residential: false,
  sponsor: "self",
};

const ENROLMENT = {
  id: 5,
  student: 9,
  student_no: "26MRP0001",
  student_name: "Ravi Singh",
  offering: 2,
  offering_code: "AGR101-2026-27-S1-MRP",
  status: "enrolled" as const,
  waitlist_rank: null,
};

const HOLD = {
  id: 3,
  student: 9,
  student_no: "26MRP0001",
  reason: "missing_document" as const,
  reason_display: "Missing document",
  source: "admissions",
  detail: "Transcript outstanding",
  is_active: true,
  resolved_at: null,
  created_at: "2026-10-01T00:00:00Z",
};

const OFFERING = {
  id: 4,
  code: "AGR102-2026-27-S1-MRP",
  course_code: "AGR102",
  course_title: "Principles of Soil Science",
  term_code: "2026-27-S1",
  campus_code: "MRP",
  lecturer_employee_no: "E0003",
  capacity: 40,
  coursework_weight: "40",
  exam_weight: "60",
  enrolled: 10,
};

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results };
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  get.mockImplementation((path: string) => {
    if (path.startsWith("/students/9/")) return Promise.resolve(STUDENT);
    if (path.startsWith("/students/")) return Promise.resolve(paginated([STUDENT]));
    if (path.startsWith("/academics/enrolments/")) return Promise.resolve(paginated([ENROLMENT]));
    if (path.startsWith("/academics/registration-holds/")) return Promise.resolve(paginated([HOLD]));
    if (path.startsWith("/academics/offerings/")) return Promise.resolve(paginated([OFFERING]));
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  post.mockResolvedValue({});
});

describe("StudentsScreen registration tab", () => {
  it("shows active holds and current enrolments, and adds a course", async () => {
    const user = userEvent.setup();
    render(<StudentsScreen me={ME} campusCode={null} initialId={null} onNavigate={() => {}} />);

    await user.click(await screen.findByText("Ravi Singh"));
    await user.click(screen.getByRole("tab", { name: "Registration" }));

    expect(await screen.findByText(/Transcript outstanding/)).toBeInTheDocument();
    expect(screen.getByText("AGR101-2026-27-S1-MRP")).toBeInTheDocument();

    const select = screen.getByLabelText("Choose an offering");
    await user.selectOptions(select, "4");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/academics/enrolments/", { student: 9, offering: 4 }));
  });

  it("drops an enrolled course", async () => {
    const user = userEvent.setup();
    render(<StudentsScreen me={ME} campusCode={null} initialId={null} onNavigate={() => {}} />);

    await user.click(await screen.findByText("Ravi Singh"));
    await user.click(screen.getByRole("tab", { name: "Registration" }));
    await user.click(await screen.findByRole("button", { name: "Drop" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/academics/enrolments/5/drop/"));
  });
});
