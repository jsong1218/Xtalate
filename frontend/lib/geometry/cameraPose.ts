import { Vec3 } from "molstar/lib/mol-math/linear-algebra.js";

/**
 * The camera-lock pose reconstruction (v2.0 addendums; item 6), extracted from the Mol* mount so it
 * can be unit-tested without a WebGL context. Imports only the pure `Vec3` linear-algebra module,
 * never the Mol* plugin, so the test stays light and this file adds nothing to the WebGL bundle.
 *
 * The lock keeps *this* viewer's own target (its structure center) and adopts the sibling's
 * orientation and distance:
 *
 *     position = localTarget + (remotePosition - remoteTarget)
 *
 * so the view direction and zoom match the sibling while the local structure stays centered.
 *
 * A degenerate remote pose — one whose position and target coincide — has *no* view direction. Left
 * unguarded it collapses `position` onto `localTarget`, and Mol*'s camera then normalizes a
 * zero-length direction vector into NaNs, blanking the canvas until a manual reset. That pose is
 * never a real orbit state, but a broadcast can carry one transiently (a snapshot taken mid-reset,
 * a not-yet-initialized camera). When the remote direction is shorter than {@link MIN_VIEW_DISTANCE}
 * we refuse it and keep the local pose unchanged — a dropped broadcast frame, never a NaN camera.
 */

/** A minimal camera pose: the two vectors the lock reconstruction reads. */
export interface CameraPose {
  readonly position: Vec3;
  readonly target: Vec3;
}

/**
 * Below this world-space distance between a pose's position and target we treat the view direction
 * as absent. Mol*'s default scene distances are on the order of tens of Å; 1e-4 is far below any
 * real orbit distance yet safely above float noise, so it rejects only genuinely degenerate poses.
 */
export const MIN_VIEW_DISTANCE = 1e-4;

/**
 * Reconstruct the local camera position that matches a remote pose's orientation and distance while
 * keeping the local target. Returns the new `position` vector, or `null` when the remote pose is
 * degenerate (no view direction) and must be ignored.
 *
 * Pure: allocates its own output and mutates neither argument.
 */
export function poseFromRemote(
  local: CameraPose,
  remote: CameraPose,
): Vec3 | null {
  const offset = Vec3.sub(Vec3.zero(), remote.position, remote.target);
  if (Vec3.magnitude(offset) < MIN_VIEW_DISTANCE) {
    return null;
  }
  return Vec3.add(Vec3.zero(), local.target, offset);
}
