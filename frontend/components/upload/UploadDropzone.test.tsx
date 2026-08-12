import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";
import { UploadDropzone, humanBytes } from "./UploadDropzone";
import tooLarge from "@/components/__fixtures__/error.file_too_large.json";

const envelope = tooLarge as unknown as ErrorEnvelopeModel;

describe("UploadDropzone (Part 7 §2.2)", () => {
  it("shows the instance size limit inline before any upload is attempted", () => {
    // The load-bearing rule: the ceiling is visible up front (Part 6 §5), not discovered by failing.
    render(
      <UploadDropzone
        maxUploadBytes={52428800}
        status="idle"
        progress={null}
        error={null}
        onFile={() => {}}
      />,
    );
    expect(screen.getByText(/up to 50 MB on this instance/i)).toBeInTheDocument();
  });

  it("shows the retention half of the limits line before any failure (Part 7 §2.2)", () => {
    render(
      <UploadDropzone
        maxUploadBytes={104857600}
        uploadRetentionHours={24}
        outputRetentionHours={24}
        status="idle"
        progress={null}
        error={null}
        onFile={() => {}}
      />,
    );
    expect(screen.getByText(/uploads deleted after 24 hours/i)).toBeInTheDocument();
    expect(screen.getByText(/outputs deleted after 24 hours/i)).toBeInTheDocument();
  });

  it("omits the limit line rather than faking a number when limits are unknown", () => {
    render(
      <UploadDropzone
        maxUploadBytes={null}
        status="idle"
        progress={null}
        error={null}
        onFile={() => {}}
      />,
    );
    expect(screen.queryByText(/on this instance/i)).not.toBeInTheDocument();
  });

  it("calls onFile with the chosen file", () => {
    const onFile = vi.fn();
    render(
      <UploadDropzone
        maxUploadBytes={52428800}
        status="idle"
        progress={null}
        error={null}
        onFile={onFile}
      />,
    );
    const input = screen.getByLabelText("Choose a file to convert") as HTMLInputElement;
    const file = new File(["1\nO 0 0 0\n"], "mol.xyz", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onFile).toHaveBeenCalledTimes(1);
    expect(onFile.mock.calls[0][0].name).toBe("mol.xyz");
  });

  it("refuses an over-limit file client-side: no onFile call, the FILE_TOO_LARGE funnel renders",
    () => {
      // v1.1 M39-S4 A2: with the live limit known and the file already over it, the drop zone must
      // not hand the file to the uploader at all — an upload would die at the proxy as an opaque
      // 500 (the D112 proxy-ceiling rule), never the backend's honest 413. The funnel renders as
      // if the server had answered, with the code verbatim.
      const onFile = vi.fn();
      render(
        <UploadDropzone
          maxUploadBytes={1024}
          status="idle"
          progress={null}
          error={null}
          onFile={onFile}
        />,
      );
      const input = screen.getByLabelText("Choose a file to convert") as HTMLInputElement;
      const big = new File(["x".repeat(2048)], "too-big.xyz", { type: "text/plain" });
      fireEvent.change(input, { target: { files: [big] } });

      expect(onFile).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("FILE_TOO_LARGE")).toBeInTheDocument();
      expect(screen.getByTestId("size-funnel")).toHaveTextContent(/no size limit/i);
    });

  it("falls through to the server-gated path when the limit is unknown", () => {
    // maxUploadBytes === null: nothing to check against — the uploader runs and the server's 413
    // stays the gate (the A2 pre-check only engages when the live limit is known).
    const onFile = vi.fn();
    render(
      <UploadDropzone
        maxUploadBytes={null}
        status="idle"
        progress={null}
        error={null}
        onFile={onFile}
      />,
    );
    const input = screen.getByLabelText("Choose a file to convert") as HTMLInputElement;
    const big = new File(["x".repeat(2048)], "too-big.xyz", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(onFile).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("size-funnel")).not.toBeInTheDocument();
  });

  it("a compliant selection after a client-side refusal clears the funnel and uploads", () => {
    const onFile = vi.fn();
    render(
      <UploadDropzone
        maxUploadBytes={1024}
        status="idle"
        progress={null}
        error={null}
        onFile={onFile}
      />,
    );
    const input = screen.getByLabelText("Choose a file to convert") as HTMLInputElement;

    fireEvent.change(input, {
      target: { files: [new File(["x".repeat(2048)], "too-big.xyz")] },
    });
    expect(screen.getByTestId("size-funnel")).toBeInTheDocument();

    fireEvent.change(input, {
      target: { files: [new File(["1\nO 0 0 0\n"], "mol.xyz")] },
    });
    expect(screen.queryByTestId("size-funnel")).not.toBeInTheDocument();
    expect(onFile).toHaveBeenCalledTimes(1);
    expect(onFile.mock.calls[0][0].name).toBe("mol.xyz");
  });

  it("renders real progress as a labelled progressbar, not a fake animation", () => {
    render(
      <UploadDropzone
        maxUploadBytes={52428800}
        status="uploading"
        progress={{ loaded: 4, total: 10, fraction: 0.4 }}
        fileName="relax.traj"
        error={null}
        onFile={() => {}}
      />,
    );
    const bar = screen.getByRole("progressbar", { name: "Upload progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("relax.traj")).toBeInTheDocument();
  });

  it("renders a failure through the shared error envelope, code verbatim", () => {
    render(
      <UploadDropzone
        maxUploadBytes={52428800}
        status="error"
        progress={null}
        error={envelope}
        onFile={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("FILE_TOO_LARGE")).toBeInTheDocument();
  });

  it("renders the self-hosting funnel on FILE_TOO_LARGE — a redirect, not a dead end", () => {
    render(
      <UploadDropzone
        maxUploadBytes={52428800}
        status="error"
        progress={null}
        error={envelope}
        onFile={() => {}}
      />,
    );
    const funnel = screen.getByTestId("size-funnel");
    expect(funnel).toHaveTextContent(/no size limit/i);
    expect(within(funnel).getByRole("link")).toHaveAttribute(
      "href",
      "https://github.com/jsong1218/Xtalate#quickstart-http-service",
    );
  });
});

describe("humanBytes", () => {
  it("renders whole and fractional sizes in the largest sensible unit", () => {
    expect(humanBytes(52428800)).toBe("50 MB");
    expect(humanBytes(40960)).toBe("40 KB");
    expect(humanBytes(512)).toBe("512 B");
    expect(humanBytes(1024 * 1024 * 1.5)).toBe("1.5 MB");
  });
});
