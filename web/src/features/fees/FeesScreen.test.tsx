import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FeesScreen } from "./FeesScreen";
import { MyBalanceScreen } from "./MyBalanceScreen";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  get,
  post,
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const STUDENT = {
  id: 9,
  student_no: "26MRP0001",
  full_name: "Ravi Singh",
  programme_code: "DIP-AGR",
  programme_name: "Diploma in Agriculture",
};

const LEDGER = {
  student_no: "26MRP0001",
  name: "Ravi Singh",
  balance: "30000.00",
  entries: [
    { kind: "charge", date: "2026-10-01", description: "Tuition (2026-27-S1)", amount: "50000.00", running_balance: "50000.00" },
    { kind: "payment", date: "2026-10-05", description: "Payment (Cash, R-001)", amount: "-20000.00", running_balance: "30000.00" },
  ],
};

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results };
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  post.mockResolvedValue({});
});

describe("FeesScreen", () => {
  it("lists students and shows the selected student's ledger", async () => {
    get.mockImplementation((path: string) => {
      if (path.startsWith("/students/")) return Promise.resolve(paginated([STUDENT]));
      if (path.startsWith("/fees/ledger/9/")) return Promise.resolve(LEDGER);
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    const user = userEvent.setup();
    render(<FeesScreen />);

    await user.click(await screen.findByText("Ravi Singh"));

    expect(await screen.findByText("Balance: 30000.00")).toBeInTheDocument();
    expect(screen.getByText("Tuition (2026-27-S1)")).toBeInTheDocument();
  });

  it("records a payment against the selected student", async () => {
    get.mockImplementation((path: string) => {
      if (path.startsWith("/students/")) return Promise.resolve(paginated([STUDENT]));
      if (path.startsWith("/fees/ledger/9/")) return Promise.resolve(LEDGER);
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    const user = userEvent.setup();
    render(<FeesScreen />);

    await user.click(await screen.findByText("Ravi Singh"));
    await screen.findByText("Balance: 30000.00");

    await user.type(screen.getByLabelText("Payment amount"), "30000");
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/fees/payments/",
        expect.objectContaining({ student: 9, amount: "30000" }),
      ),
    );
  });
});

describe("MyBalanceScreen", () => {
  it("shows the signed-in student's own balance", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/fees/my-balance/") return Promise.resolve(LEDGER);
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    render(<MyBalanceScreen />);

    expect(await screen.findByText("Balance: 30000.00")).toBeInTheDocument();
  });
});
