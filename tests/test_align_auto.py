"""Tests of the automatic alignment (AlignGen.auto_align) on synthetic boards: holes must fall into pads."""

import math
import os
import sys
import time
import unittest

import numpy as np
import pytest
from shapely import Point, box

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from appPlugins.ToolAlignObjects.AlignGen import (AlignError, SnapIndex, auto_align, bounded_align, is_ambiguous, apply_matrix,
                                                  invert)


def board(seed=1, vias=60):
    """Pad centers of a board: 3 DIP footprints, 2 rows of headers, random vias. Not symmetric."""
    rng = np.random.default_rng(seed)
    pts = []
    for ox, oy, n in ((5, 5, 8), (30, 8, 14), (12, 40, 4)):
        for i in range(n):
            pts.append((ox + i * 2.54, oy))
            pts.append((ox + i * 2.54, oy + 7.62))
    for i in range(10):
        pts.append((60, 5 + i * 2.54))
    pts.extend(rng.uniform((0, 0), (80, 60), (vias, 2)).tolist())
    return np.array(pts)


def pad_index(centers, size=1.6):
    solids = [box(x - size / 2, y - size / 2, x + size / 2, y + size / 2) for x, y in centers]
    return SnapIndex(solids, centers, np.empty((0, 2)))


def hole_index(centers, dia=0.8):
    return SnapIndex([Point(x, y).buffer(dia / 2) for x, y in centers], centers, np.empty((0, 2)))


def rot(angle_deg, dx, dy, s=1.0):
    t = math.radians(angle_deg)
    return s * math.cos(t), -s * math.sin(t), s * math.sin(t), s * math.cos(t), dx, dy


def smd_board():
    """Sparse irregular through holes surrounded by many much closer, unrelated SMD flashes."""
    through = np.array([(0, 0), (8, 1), (21, 0), (3, 12), (15, 9), (31, 7),
                        (1, 25), (13, 22), (26, 19), (38, 28), (8, 37), (29, 39)], dtype=float)
    smd = np.vstack([p + np.random.default_rng(i).uniform((1, 1), (3, 3), (20, 2))
                     for i, p in enumerate(through)])
    centers = np.vstack([through, smd])
    pads = SnapIndex([Point(p).buffer(0.8) for p in through] +
                    [box(x - 0.1, y - 0.15, x + 0.1, y + 0.15) for x, y in smd], centers, [])
    pads.kind = 'gerber'
    matrix = rot(37, 57, -23)
    # Two non-plated holes have no copper pad; neither should invalidate the twelve real correspondences.
    holes = hole_index(apply_matrix(invert(matrix), np.vstack([through, [(70, 65), (-25, 60)]])))
    holes.kind = 'excellon'
    return through, pads, holes, matrix


def partial_smd_board():
    """Mounting/tooling holes and SMD pads are both mostly unmatched; only twelve points are common."""
    through, pads, holes, matrix = smd_board()
    candidates = np.random.default_rng(81).uniform((-20, -20), (60, 60), (200, 2))
    distances = np.linalg.norm(candidates[:, None, :] - pads.centers[None, :, :], axis=2)
    mounting = candidates[distances.min(axis=1) > 1.5][:30]
    holes = hole_index(np.vstack([holes.centers, apply_matrix(invert(matrix), mounting)]))
    holes.kind = 'excellon'
    return through, pads, holes, matrix


@pytest.mark.parametrize('reverse', [False, True])
def test_partial_correspondence_uses_common_subset_not_global_hole_fraction(reverse):
    through, pads, holes, matrix = partial_smd_board()
    results = auto_align(pads, holes) if reverse else auto_align(holes, pads)
    best = results[0]
    assert (best.matched, best.total) == (12, 44)
    assert not is_ambiguous(results)
    moving = pads.centers[:12] if reverse else holes.centers[:12]
    expected = holes.centers[:12] if reverse else through
    np.testing.assert_allclose(apply_matrix(best.matrix, moving), expected, atol=0.02)


@pytest.mark.parametrize('unmatched', [False, True])
def test_centered_translation_is_only_a_seed_and_preserves_current_alignment(unmatched):
    points = np.random.default_rng(92).uniform((100, -80), (150, -30), (40, 2))
    target = np.vstack([points, [(400, 500)]]) if unmatched else points
    pads = pad_index(target)
    pads.kind = 'gerber'
    holes = hole_index(points + (135, -222))
    holes.kind = 'excellon'
    original = holes.centers.copy()
    result = auto_align(holes, pads, allow_mirror=True)
    assert not is_ambiguous(result)
    assert result[0].matched == 40
    np.testing.assert_allclose(apply_matrix(result[0].matrix, original), points, atol=1e-8)
    np.testing.assert_array_equal(holes.centers, original)
    current = hole_index(points)
    current.kind = 'excellon'
    result = auto_align(current, pads, allow_mirror=True)
    np.testing.assert_allclose(apply_matrix(result[0].matrix, points), points, atol=1e-8)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('noise', [0, 0.01])
def test_smd_alignment_counts_holes_and_maps_preview_in_motion_direction(reverse, noise):
    through, pads, holes, matrix = smd_board()
    if noise:
        holes.centers += np.random.default_rng(9).normal(0, noise, holes.centers.shape)
    results = auto_align(pads, holes) if reverse else auto_align(holes, pads)
    best = results[0]
    assert best.total == len(holes.centers), (best.matched, best.total)
    assert best.matched == len(through), (best.matched, best.total, best.matrix)
    assert best.matched == len(best.P) == len(best.Q)
    assert not is_ambiguous(results)
    want = invert(matrix) if reverse else matrix
    moving = pads.centers[:len(through)] if reverse else holes.centers[:len(through)]
    np.testing.assert_allclose(apply_matrix(best.matrix, moving), apply_matrix(want, moving), atol=0.02)
    np.testing.assert_allclose(apply_matrix(best.matrix, best.P), best.Q, atol=0.03)


@pytest.mark.parametrize('mirrored', [False, True])
@pytest.mark.parametrize('parallel', [False, True])
def test_dblsided_smd_alignment_uses_drill_coverage_for_both_layers(mirrored, parallel):
    from appPlugins.ToolDblSided.DblSidedGen import alignment_matrices
    through, pads, holes, matrix = partial_smd_board()
    bottom_matrix = rot(-19, 11, 6)
    if mirrored:
        bottom_matrix = (-bottom_matrix[0], bottom_matrix[1], -bottom_matrix[2], *bottom_matrix[3:])
    from shapely.affinity import affine_transform
    bottom = SnapIndex([affine_transform(g, bottom_matrix) for g in pads.tree.geometries],
                       apply_matrix(bottom_matrix, pads.centers), [])
    bottom.kind = 'gerber'
    original = [index.centers.copy() for index in (pads, bottom, holes)]
    matrices = alignment_matrices([pads, bottom, holes], [0, 1], 2, parallel=parallel)
    np.testing.assert_allclose(apply_matrix(matrices[2], holes.centers[:len(through)]), through, atol=0.02)
    np.testing.assert_allclose(apply_matrix(matrices[1], bottom.centers[:len(through)]), through, atol=0.02)
    for index, centers in zip((pads, bottom, holes), original):
        np.testing.assert_array_equal(index.centers, centers)


def test_smd_alignment_rejects_genuinely_repeated_hole_patterns():
    from appPlugins.ToolDblSided.DblSidedGen import alignment_matrices
    through, pads, holes, matrix = partial_smd_board()
    repeated = through + (100, 0)
    pads = SnapIndex(list(pads.tree.geometries) + [Point(p).buffer(0.8) for p in repeated],
                     np.vstack([pads.centers, repeated]), [], kind='gerber')
    results = auto_align(holes, pads)
    assert results[0].matched == len(through)
    assert is_ambiguous(results)
    with pytest.raises(AlignError, match='ambiguous'):
        alignment_matrices([pads, holes], [0], 1)


@pytest.mark.parametrize('crowded', [False, True])
@pytest.mark.parametrize('matcher', [auto_align, bounded_align])
def test_centered_perfect_fit_still_reports_competing_patterns(crowded, matcher):
    through = np.array([(0, 0), (3, 1), (8, 4), (2, 9), (7, 11)], dtype=float)
    centers = np.vstack([through + (-100, 0), through, through + (100, 0)])
    if crowded:
        # More than 128 centers in an X slab exercises the bounded-memory tree fallback.
        centers = np.vstack([centers, np.column_stack([np.full(130, 4), np.linspace(-300, 311, 130)])])
    pads = pad_index(centers)
    pads.kind = 'gerber'
    holes = hole_index(through)
    holes.kind = 'excellon'
    results = matcher(holes, pads, allow_mirror=True)
    assert results[0].matched == len(through)
    assert is_ambiguous(results)


@pytest.mark.parametrize('points', [[(1000, 1000)], [(1000, 1000), (1200, 1000)]])
def test_dblsided_rejects_inadequate_geometric_evidence_not_low_coverage(points):
    from appPlugins.ToolDblSided.DblSidedGen import alignment_matrices
    through, pads, holes, matrix = smd_board()
    holes = hole_index(np.asarray(points))
    holes.kind = 'excellon'
    with pytest.raises(AlignError):
        auto_align(holes, pads)
    with pytest.raises(AlignError):
        alignment_matrices([pads, holes], [0], 1)


def test_dblsided_reports_competing_two_point_fits_instead_of_guessing():
    from appPlugins.ToolDblSided.DblSidedGen import alignment_matrices
    through, pads, holes, matrix = partial_smd_board()
    holes = hole_index(holes.centers[:2])
    holes.kind = 'excellon'
    results = auto_align(holes, pads)
    assert (results[0].matched, results[0].total) == (2, 2)
    assert is_ambiguous(results)
    with pytest.raises(AlignError, match='ambiguous'):
        alignment_matrices([pads, holes], [0], 1)


@pytest.mark.parametrize('reverse', [False, True])
def test_smd_pad_density_does_not_make_inferior_center_fits_ambiguous(reverse):
    through, pads, holes, matrix = partial_smd_board()
    pads = pad_index(pads.centers)
    pads.kind = 'gerber'
    results = auto_align(pads, holes) if reverse else auto_align(holes, pads)
    assert results[0].matched == len(through)
    moving = pads.centers[:12] if reverse else holes.centers[:12]
    expected = holes.centers[:12] if reverse else through
    np.testing.assert_allclose(apply_matrix(results[0].matrix, moving), expected, atol=0.02)
    assert not is_ambiguous(results)


@pytest.mark.parametrize('reverse', [False, True])
def test_smd_mirrored_fit_keeps_motion_direction_and_hole_counts(reverse):
    through, pads, holes, matrix = smd_board()
    holes = hole_index(holes.centers * (-1, 1))
    holes.kind = 'excellon'
    results = auto_align(pads, holes, allow_mirror=True) if reverse else auto_align(holes, pads, allow_mirror=True)
    best = results[0]
    assert best.mirrored and (best.matched, best.total) == (12, 14)
    assert not is_ambiguous(results)
    moving = pads.centers[:12] if reverse else holes.centers[:12]
    expected = holes.centers[:12] if reverse else through
    np.testing.assert_allclose(apply_matrix(best.matrix, moving), expected, atol=0.02)


@pytest.mark.parametrize('kind', ['gerber', 'excellon'])
def test_same_type_auto_alignment_retains_center_coverage_and_ambiguity(kind):
    through, _pads, _holes, matrix = smd_board()
    factory = pad_index if kind == 'gerber' else hole_index
    source = factory(apply_matrix(invert(matrix), through))
    target = factory(through)
    source.kind = target.kind = kind
    best = auto_align(source, target)[0]
    assert (best.matched, best.total) == (len(through), len(through))
    np.testing.assert_allclose(apply_matrix(best.matrix, source.centers), through, atol=0.02)
    repeated = factory(np.vstack([through, through + (100, 0)]))
    repeated.kind = kind
    assert is_ambiguous(auto_align(source, repeated))


@pytest.mark.parametrize('mirrored', [False])
def test_dense_pad_arrays_keep_drill_registration_and_competing_placements(mirrored):
    rng = np.random.default_rng(412)
    through = rng.uniform((0, 0), (120, 80), (200, 2))
    smd = np.vstack([np.column_stack([x + np.arange(40) * 0.5, np.full(40, y)])
                     for x, y in rng.uniform((0, 0), (95, 80), (20, 2))])
    pads = pad_index(np.vstack([through, smd]), size=0.25)
    pads.kind = 'gerber'
    flip = (-1, 1) if mirrored else (1, 1)
    holes = hole_index((through + (17, -23)) * flip)
    holes.kind = 'excellon'
    results = auto_align(holes, pads, allow_mirror=True)
    assert results[0].matched == len(through)
    assert not is_ambiguous(results)
    np.testing.assert_allclose(apply_matrix(results[0].matrix, holes.centers), through, atol=1e-8)
    repeated = pad_index(np.vstack([pads.centers, through[:190] + (150, 0)]), size=0.25)
    repeated.kind = 'gerber'
    assert is_ambiguous(auto_align(holes, repeated, allow_mirror=True))


@pytest.mark.parametrize('crowded_rotated', [False, True])
@pytest.mark.parametrize('matcher', [auto_align, bounded_align])
def test_exact_partial_local_fit_does_not_hide_a_better_noisy_placement(crowded_rotated, matcher):
    rng = np.random.default_rng(73)
    points = rng.uniform((0, 0), (50, 40), (40, 2))
    if crowded_rotated:
        angle = np.deg2rad(37)
        rotation = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
        noisy_copy = points @ rotation + (120, 80) + rng.normal(0, 0.01, points.shape)
        placements = [noisy_copy, noisy_copy + (0.15, 0.15)]
    else:
        noisy_copy = points + (120, 80) + rng.normal(0, 0.02, points.shape)
        placements = [noisy_copy]
    pads = pad_index(np.vstack([points[:34], *placements]), size=0.25 if crowded_rotated else 1.6)
    pads.kind = 'gerber'
    holes = hole_index(points)
    holes.kind = 'excellon'
    result = matcher(holes, pads, allow_mirror=True)
    assert result[0].matched == len(points)
    moved = apply_matrix(result[0].matrix, points)
    assert min(float(np.linalg.norm(moved - target, axis=1).max()) for target in placements) < 0.07
    assert is_ambiguous(result) == crowded_rotated


@pytest.mark.parametrize('mirrored', [False, True])
def test_bounded_registration_partial_features_and_original_snapshots(mirrored):
    from appPlugins.ToolAlignObjects.AlignGen import bounded_align
    through, pads, holes, matrix = partial_smd_board()
    if mirrored:
        holes = hole_index(holes.centers * (-1, 1))
        holes.kind = 'excellon'
    original = holes.centers.copy()
    results = bounded_align(holes, pads, allow_mirror=True)
    assert results[0].matched == len(through)
    assert not is_ambiguous(results)
    np.testing.assert_allclose(apply_matrix(results[0].matrix, original[:12]), through, atol=0.02)
    np.testing.assert_array_equal(holes.centers, original)


def test_bounded_registration_keeps_lower_support_exact_competing_placement():
    from appPlugins.ToolDblSided.DblSidedGen import alignment_matrices
    rng = np.random.default_rng(902)
    points = rng.uniform((0, 0), (30, 25), (20, 2))
    placements = [points + (100 * i, 0) + rng.normal(0, 0.002 * (i + 1), points.shape)
                  for i in range(5)]
    centers = np.vstack([*placements, points[:19] + (500, 0)])
    pads = SnapIndex([Point(p).buffer(0.8) for p in centers], centers, [], kind='gerber')
    holes = hole_index(points)
    holes.kind = 'excellon'
    results = bounded_align(holes, pads, allow_mirror=True)
    assert results[0].matched == len(points)
    assert is_ambiguous(results)
    with pytest.raises(AlignError, match='ambiguous'):
        alignment_matrices([pads, holes], [0], 1, parallel=False)


@pytest.mark.parametrize('model,matrix,limit', [
    ('rigid', rot(37, 15, -7), 2),
    ('similarity', rot(0, 0.2, -0.1, s=1.015), 2),
    ('affine', (1.01, 0.015, -0.01, 0.99, 0.2, -0.1), 3),
])
def test_pair_limit_fits_selected_model_and_verifies_every_feature(model, matrix, limit, monkeypatch):
    import appPlugins.ToolAlignObjects.AlignGen as gen
    fits = []
    for name in ('solve_rigid', 'solve_similarity', 'solve_affine'):
        solver = getattr(gen, name)
        def capped(P, Q, solver=solver):
            assert len(P) == len(Q) <= limit
            fits.append(len(P))
            return solver(P, Q)
        monkeypatch.setattr(gen, name, capped)
    points = board(vias=15)
    result = auto_align(hole_index(points), pad_index(apply_matrix(matrix, points)),
                        model=model, pair_limit=limit)[0]
    assert result.matched == result.total == len(points)
    assert len(result.P) == len(result.errors) == len(points)
    assert len(result.fit_P) == len(result.fit_Q) == limit
    assert fits
    np.testing.assert_allclose(apply_matrix(result.matrix, points), apply_matrix(matrix, points), atol=1e-7)
    # The actual solver evidence spans the board, not the first footprint in input order.
    assert np.ptp(result.fit_P, axis=0).max() > 40
    solver = {'rigid': gen.solve_rigid, 'similarity': gen.solve_similarity, 'affine': gen.solve_affine}[model]
    np.testing.assert_allclose(solver(result.fit_P, result.fit_Q), result.matrix, atol=1e-7)


@pytest.mark.parametrize('reverse', [False, True])
def test_pair_limit_mixed_motion_keeps_full_support_and_actual_fit_pairs(reverse):
    through, pads, holes, matrix = smd_board()
    results = auto_align(pads, holes, pair_limit=6) if reverse else auto_align(holes, pads, pair_limit=6)
    result = results[0]
    assert (result.matched, result.total) == (12, 14)
    assert len(result.fit_P) == len(result.fit_Q) == 6
    np.testing.assert_allclose(apply_matrix(result.matrix, result.fit_P), result.fit_Q, atol=1e-7)
    assert not is_ambiguous(results)


@pytest.mark.parametrize('model,limit', [('rigid', 1), ('similarity', 1), ('affine', 2)])
def test_pair_limit_rejects_less_than_model_minimum(model, limit):
    with pytest.raises(AlignError, match='pairs'):
        auto_align(hole_index(board()), pad_index(board()), model=model, pair_limit=limit)


def test_zero_pair_limit_is_the_original_search():
    source, target = hole_index(board()), pad_index(board())
    old, zero = auto_align(source, target), auto_align(source, target, pair_limit=0)
    assert [(r.matrix, r.matched, r.rms) for r in old] == [(r.matrix, r.matched, r.rms) for r in zero]


def test_limited_fit_keeps_full_residuals_and_competing_placements():
    points = np.random.default_rng(310).uniform((0, 0), (30, 25), (20, 2))
    noisy = points + np.random.default_rng(312).normal(0, 0.01, points.shape)
    target = pad_index(np.vstack([noisy, noisy + (100, 0)]))
    results = auto_align(hole_index(points), target, pair_limit=6)
    best = results[0]
    assert best.matched == best.total == len(points)
    assert len(best.errors) == len(points) > len(best.fit_P)
    errors = np.linalg.norm(apply_matrix(best.matrix, best.P) - best.Q, axis=1)
    np.testing.assert_allclose(best.errors, errors)
    assert best.rms == pytest.approx(np.sqrt(np.mean(errors ** 2)))
    assert is_ambiguous(results)


class TestAutoAlign(unittest.TestCase):

    def check(self, holes, pads, want, **kw):
        """want: the matrix that maps the holes onto the pads."""
        t0 = time.perf_counter()
        res = auto_align(hole_index(holes), pad_index(pads), **kw)
        took = time.perf_counter() - t0
        best = res[0]
        err = np.hypot(*(apply_matrix(best.matrix, holes) - apply_matrix(want, holes)).T)
        self.assertLess(float(err.max()), 0.05, 'max error %.4f' % err.max())
        self.assertLess(took, 5.0)
        return best

    def test_rotations(self):
        pads = board()
        for ang in (0, 37, 90, 180, -123.4):
            with self.subTest(angle=ang):
                m = rot(ang, 15.0, -7.5)
                holes = apply_matrix(invert(m), pads)
                best = self.check(holes, pads, m)
                self.assertEqual(best.matched, len(holes))
                self.assertFalse(best.mirrored)

    def test_mirror(self):
        pads = board()
        m = rot(25, 100.0, 3.0)
        mirrored = (-m[0], m[1], -m[2], m[3], m[4], m[5])    # m after x -> -x
        holes = apply_matrix(invert(mirrored), pads)
        best = self.check(holes, pads, mirrored, allow_mirror=True)
        self.assertTrue(best.mirrored)
        with self.assertRaises(AssertionError):
            self.check(holes, pads, mirrored, allow_mirror=False)

    def test_outliers_and_missing_pads(self):
        rng = np.random.default_rng(5)
        pads = board(vias=80)
        m = rot(-71, -20.0, 40.0)
        holes = apply_matrix(invert(m), pads)
        holes = holes[rng.permutation(len(holes))[: int(0.85 * len(holes))]]     # pads with no hole
        extra = rng.uniform(holes.min(axis=0), holes.max(axis=0), (15, 2))        # holes with no pad
        noisy = np.vstack([holes, extra]) + rng.normal(0, 0.02, (len(holes) + 15, 2))
        best = self.check(noisy, pads, m)
        self.assertGreaterEqual(best.matched, len(holes) - 2)
        self.assertLess(best.rms, 0.06)

    def test_errors(self):
        with self.assertRaises(AlignError):
            auto_align(hole_index(np.array([(0.0, 0.0)])), pad_index(board()))
        with self.assertRaises(AlignError):
            auto_align(hole_index(board()), SnapIndex([], [], np.empty((0, 2))))

if __name__ == '__main__':
    unittest.main()
