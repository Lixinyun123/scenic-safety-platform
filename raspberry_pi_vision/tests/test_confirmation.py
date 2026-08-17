import unittest

from detection_logic import PersonConfirmer


class PersonConfirmerTest(unittest.TestCase):
    def test_requires_consecutive_frames(self) -> None:
        confirmer = PersonConfirmer(required_frames=3)
        self.assertFalse(confirmer.update(True).confirmed)
        self.assertFalse(confirmer.update(True).confirmed)
        state = confirmer.update(True)
        self.assertTrue(state.confirmed)
        self.assertTrue(state.just_confirmed)

    def test_missing_frame_resets_counter(self) -> None:
        confirmer = PersonConfirmer(required_frames=2)
        confirmer.update(True)
        state = confirmer.update(False)
        self.assertEqual(state.consecutive_frames, 0)
        self.assertFalse(state.confirmed)

    def test_alert_edge_occurs_once(self) -> None:
        confirmer = PersonConfirmer(required_frames=1)
        self.assertTrue(confirmer.update(True).just_confirmed)
        self.assertFalse(confirmer.update(True).just_confirmed)
        confirmer.update(False)
        self.assertTrue(confirmer.update(True).just_confirmed)


if __name__ == "__main__":
    unittest.main()

