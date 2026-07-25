import { fireEvent, render, screen } from "@testing-library/react";
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
});

describe("humanBytes", () => {
  it("renders whole and fractional sizes in the largest sensible unit", () => {
    expect(humanBytes(52428800)).toBe("50 MB");
    expect(humanBytes(40960)).toBe("40 KB");
    expect(humanBytes(512)).toBe("512 B");
    expect(humanBytes(1024 * 1024 * 1.5)).toBe("1.5 MB");
  });
});
