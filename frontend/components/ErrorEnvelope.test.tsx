import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";
import { ErrorEnvelope } from "./ErrorEnvelope";
import tooLarge from "./__fixtures__/error.file_too_large.json";

const envelope = tooLarge as unknown as ErrorEnvelopeModel;

describe("ErrorEnvelope (Part 6 §6)", () => {
  it("shows the machine code verbatim — never paraphrased", () => {
    render(<ErrorEnvelope envelope={envelope} />);
    expect(screen.getByText("FILE_TOO_LARGE")).toBeInTheDocument();
    expect(screen.getByText(envelope.error.message)).toBeInTheDocument();
  });

  it("surfaces the request_id as the bridge to the server log", () => {
    render(<ErrorEnvelope envelope={envelope} />);
    expect(screen.getByText(envelope.error.request_id)).toBeInTheDocument();
  });

  it("renders structured details when present", () => {
    render(<ErrorEnvelope envelope={envelope} />);
    expect(screen.getByText("limit_bytes")).toBeInTheDocument();
    expect(screen.getByText("52428800")).toBeInTheDocument();
  });

  it("is announced to assistive tech as an alert", () => {
    render(<ErrorEnvelope envelope={envelope} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("FILE_TOO_LARGE")).toBeInTheDocument();
  });

  it("shows no details block when details is empty", () => {
    const noDetails: ErrorEnvelopeModel = {
      error: { ...envelope.error, code: "OUTPUT_EXPIRED", details: {} },
    };
    render(<ErrorEnvelope envelope={noDetails} />);
    expect(screen.getByText("OUTPUT_EXPIRED")).toBeInTheDocument();
    expect(screen.queryByText("max_upload_bytes")).not.toBeInTheDocument();
  });
});
