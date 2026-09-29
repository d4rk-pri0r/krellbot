import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobsDrawer } from "./JobsDrawer";

afterEach(cleanup);

describe("JobsDrawer", () => {
  it("shows a job returned by the client", async () => {
    render(
      <JobsDrawer
        client={{
          list: vi.fn().mockResolvedValue([
            { id: "job-1", kind: "research.backtest", state: "succeeded" },
          ]),
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
    expect((await screen.findByTestId("job-row")).textContent).toContain("job-1 succeeded");
    expect(screen.queryByText("No jobs")).toBeNull();
  });
});
