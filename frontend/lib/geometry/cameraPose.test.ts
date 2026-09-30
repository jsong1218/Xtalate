import { Vec3 } from "molstar/lib/mol-math/linear-algebra.js";
import { describe, expect, it } from "vitest";

import { MIN_VIEW_DISTANCE, poseFromRemote } from "./cameraPose";

/**
 * The camera-lock pose reconstruction (v2.0 addendums; item 6). These run without a WebGL context —
 * `poseFromRemote` is pure and depends only on `Vec3`.
 */
describe("poseFromRemote", () => {
  it("adopts the remote orientation and distance while keeping the local target", () => {
    const local: { position: Vec3; target: Vec3 } = {
      position: Vec3.create(0, 0, 5),
      target: Vec3.create(0, 0, 0),
    };
    // Remote looks down +x from distance 10, centered on a different structure at (100,0,0).
    const remote = {
      position: Vec3.create(110, 0, 0),
      target: Vec3.create(100, 0, 0),
    };

    const position = poseFromRemote(local, remote);
    expect(position).not.toBeNull();
    // position = localTarget + (remotePosition - remoteTarget) = (0,0,0) + (10,0,0)
    expect(Array.from(position!)).toEqual([10, 0, 0]);
    // Distance from the LOCAL target matches the remote's distance (zoom is mirrored).
    expect(Vec3.distance(position!, local.target)).toBeCloseTo(10, 6);
  });

  it("returns null for a degenerate remote pose (position === target)", () => {
    const local = {
      position: Vec3.create(0, 0, 5),
      target: Vec3.create(0, 0, 0),
    };
    const remote = {
      position: Vec3.create(3, 3, 3),
      target: Vec3.create(3, 3, 3),
    };

    // No view direction: reconstructing would collapse position onto the local target and hand
    // Mol* a zero-length direction to normalize into NaNs. The lock must drop this frame.
    expect(poseFromRemote(local, remote)).toBeNull();
  });

  it("returns null just below the minimum view distance and a vector at it", () => {
    const local = {
      position: Vec3.create(0, 0, 5),
      target: Vec3.create(0, 0, 0),
    };
    const below = {
      position: Vec3.create(0, 0, MIN_VIEW_DISTANCE / 2),
      target: Vec3.zero(),
    };
    const at = {
      position: Vec3.create(0, 0, MIN_VIEW_DISTANCE * 2),
      target: Vec3.zero(),
    };

    expect(poseFromRemote(local, below)).toBeNull();
    expect(poseFromRemote(local, at)).not.toBeNull();
  });

  it("does not mutate either argument", () => {
    const local = {
      position: Vec3.create(0, 0, 5),
      target: Vec3.create(1, 2, 3),
    };
    const remote = {
      position: Vec3.create(20, 0, 0),
      target: Vec3.create(10, 0, 0),
    };
    const localBefore = Vec3.clone(local.target);
    const remotePosBefore = Vec3.clone(remote.position);

    poseFromRemote(local, remote);

    expect(Array.from(local.target)).toEqual(Array.from(localBefore));
    expect(Array.from(remote.position)).toEqual(Array.from(remotePosBefore));
  });
});
