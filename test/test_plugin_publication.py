import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock


class TestPluginPublication(TestCase):
    def test_failed_copy_does_not_leave_partial_output(self):
        from ogre.plugin_publication import publish_files

        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage, output = root / "stage", root / "output"
            stage.mkdir()
            output.mkdir()
            (stage / "result").write_bytes(b"parsed evidence")

            def failed_copy(origin, destination, **kwargs):
                destination.write(b"partial")
                raise OSError(errno.ENOSPC, "Disk full")

            with mock.patch(
                "ogre.plugin_publication.os.link",
                side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
            ):
                with mock.patch(
                    "ogre.plugin_publication.shutil.copyfileobj",
                    side_effect=failed_copy,
                ):
                    with self.assertRaises(OSError):
                        publish_files(stage, output)
            self.assertEqual(list(output.iterdir()), [])

    def test_publication_rolls_back_own_files_after_concurrent_collision(self):
        from ogre.plugin_publication import publish_files

        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage, output = root / "stage", root / "output"
            stage.mkdir()
            output.mkdir()
            (stage / "first").write_bytes(b"first result")
            (stage / "second").write_bytes(b"second result")
            link = os.link

            def race(source, target):
                if Path(target).name == "second":
                    Path(target).write_bytes(b"concurrent evidence")
                link(source, target)

            with mock.patch("ogre.plugin_publication.os.link", side_effect=race):
                with self.assertRaises(FileExistsError):
                    publish_files(stage, output)
            self.assertEqual(
                {path.name: path.read_bytes() for path in output.iterdir()},
                {"second": b"concurrent evidence"},
            )

    def test_filesystems_without_hard_links_use_exclusive_copy(self):
        from ogre.plugin_publication import publish_files

        cases = [
            (collision, error)
            for collision in (False, True)
            for error in (errno.EOPNOTSUPP, errno.EINVAL)
        ]
        for collision, error in cases:
            with (
                self.subTest(collision=collision, error=error),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                stage, output = root / "stage", root / "output"
                stage.mkdir()
                output.mkdir()
                (stage / "result").write_bytes(b"parsed evidence")

                def unsupported(source, target):
                    if collision:
                        Path(target).write_bytes(b"existing evidence")
                    raise OSError(error, "Hard links unsupported")

                with mock.patch(
                    "ogre.plugin_publication.os.link", side_effect=unsupported
                ):
                    if collision:
                        with self.assertRaises(FileExistsError):
                            publish_files(stage, output)
                    else:
                        publish_files(stage, output)
                expected = b"existing evidence" if collision else b"parsed evidence"
                self.assertEqual((output / "result").read_bytes(), expected)
