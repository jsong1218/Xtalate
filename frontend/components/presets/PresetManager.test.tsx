import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PresetManager } from "./PresetManager";
import { savePreset } from "@/lib/prefs/presets";

/**
 * Saved-conversion presets (S4, D246) — the persistence is `lib/prefs/presets.ts` (tested there);
 * here the component contract: it saves the picker's current (target, mode) under a name, lists
 * saved presets, re-converts from one, and deletes — all replaying the target + posture, and the
 * caller's `onConvert` being the only network touch (the app's POST /v1/convert, which pauses for
 * any file-specific recovery).
 */
afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function renderManager(overrides: Partial<Parameters<typeof PresetManager>[0]> = {}) {
  const onConvert = vi.fn();
  const defaults = {
    currentSelection: { target: "poscar", mode: "strict" } as const,
    targetName: "POSCAR",
    onConvert,
  };
  render(<PresetManager {...defaults} {...overrides} />);
  return { onConvert };
}

describe("PresetManager", () => {
  it("renders nothing with no presets and no selection yet", () => {
    const { container } = render(
      <PresetManager currentSelection={null} targetName={null} onConvert={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("saves the current selection under a typed name", () => {
    renderManager();
    fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "Print-ready" } });
    fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
    expect(screen.getByRole("status")).toHaveTextContent(/Saved “Print-ready”/);
    // The list now shows the preset, with its target + mode posture.
    expect(screen.getByTestId("preset-list").textContent).toMatch(/Print-ready/);
    expect(screen.getByTestId("preset-list").textContent).toMatch(/POSCAR/);
    expect(screen.getByTestId("preset-list").textContent).toMatch(/strict/);
  });

  it("re-converts a saved preset through the caller's onConvert", () => {
    savePreset({
      name: "poscar-strict",
      target_format_id: "poscar",
      target_format_name: "POSCAR",
      mode: "strict",
    });
    const { onConvert } = renderManager();
    fireEvent.click(screen.getByRole("button", { name: "Re-convert" }));
    expect(onConvert).toHaveBeenCalledWith("poscar", "strict");
  });

  it("deletes a saved preset", () => {
    const { presets } = savePreset({
      name: "temp",
      target_format_id: "cif",
      target_format_name: "CIF",
      mode: "permissive",
    });
    const { onConvert } = renderManager();
    fireEvent.click(screen.getByRole("button", { name: `Delete preset ${presets[0].name}` }));
    expect(onConvert).not.toHaveBeenCalled();
    expect(screen.queryByText("temp")).not.toBeInTheDocument();
  });
});