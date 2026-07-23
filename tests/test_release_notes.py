from __future__ import annotations

import unittest

from vrctool_app.release_notes import current_release_notes, should_show_release_notes


class ReleaseNotesTests(unittest.TestCase):
    def test_current_version_is_shown_until_user_dismisses_it(self) -> None:
        notes = current_release_notes()
        version = notes["version"]
        self.assertTrue(should_show_release_notes(version, ""))
        self.assertFalse(should_show_release_notes(version, version))

    def test_new_version_resets_previous_dismissal(self) -> None:
        self.assertTrue(should_show_release_notes("2.3.3", "2.3.2"))

    def test_callers_cannot_mutate_shared_release_notes(self) -> None:
        notes = current_release_notes()
        notes["items"].clear()
        self.assertTrue(current_release_notes()["items"])

    def test_lyrics_support_is_explained_in_plain_language(self) -> None:
        notes = current_release_notes()
        text = " ".join([notes["title"], *notes["items"]])
        self.assertIn("QQ 音乐和汽水音乐现在支持显示歌词", text)
        self.assertIn("网易云音乐和酷狗音乐暂不支持歌词", text)
        for technical_term in ("Windows", "媒体会话", "接口", "LRCLIB", "时间轴", "匹配"):
            self.assertNotIn(technical_term, text)


if __name__ == "__main__":
    unittest.main()
