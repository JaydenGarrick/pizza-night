"""Unreal -> glTF coordinate conversion and skeleton math.

Unreal (UE2): left-handed, X forward, Y right, Z up.
glTF: right-handed, X right, Y up, -Z forward.
   gltf = (ue.y, ue.z, -ue.x)
"""
import numpy as np

M = np.array([[0, 1, 0], [0, 0, 1], [-1, 0, 0]], dtype=np.float64)  # gltf = M @ ue


def vec(v):
    v = np.asarray(v, dtype=np.float64)
    return v @ M.T


def quat(q, conj=False):
    """Unreal quat (x,y,z,w) -> glTF quat (x,y,z,w) under the basis change M (improper).
    q' = (-qy, -qz, qx, w) ; conj flips the vector part first."""
    q = np.asarray(q, dtype=np.float64)
    x, y, z, w = (q[..., 0], q[..., 1], q[..., 2], q[..., 3])
    if conj:
        x, y, z = -x, -y, -z
    out = np.stack([-y, -z, x, w], axis=-1)
    # normalize
    n = np.linalg.norm(out, axis=-1, keepdims=True)
    return out / np.where(n == 0, 1, n)


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def quat_mul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def trs(t, q):
    m = np.eye(4); m[:3, :3] = quat_to_mat(q); m[:3, 3] = t
    return m


def world_matrices(bones, local_t, local_q):
    """bones: list with 'parent' indices (root has parent 0 == itself). Returns list of 4x4."""
    out = [None] * len(bones)
    for i, b in enumerate(bones):
        loc = trs(local_t[i], local_q[i])
        p = b["parent"]
        out[i] = loc if i == 0 else out[p] @ loc
    return out


def quat_from_mat(R):
    """3x3 rotation matrix -> quaternion (x, y, z, w)."""
    R = np.asarray(R, dtype=np.float64); tr = np.trace(R)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2; return np.array([(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s])
    i = int(np.argmax([R[0, 0], R[1, 1], R[2, 2]]))
    if i == 0:
        s = np.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; return np.array([0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s])
    if i == 1:
        s = np.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; return np.array([(R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s])
    s = np.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; return np.array([(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s, (R[1, 0] - R[0, 1]) / s])
