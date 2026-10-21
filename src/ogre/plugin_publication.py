"""Publish a plugin's completed files without appending to existing evidence."""

import copy
import errno
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def publish_files(stage: Path, output: Path) -> None:
    sources = sorted(path for path in stage.rglob("*") if not path.is_dir())
    targets = [output / path.relative_to(stage) for path in sources]
    for source, target in zip(sources, targets):
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Plugin output must be a regular file: {source}")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Output already exists: {target}")

    created = []
    try:
        for source, target in zip(sources, targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
            except OSError as error:
                if error.errno not in (
                    errno.EXDEV,
                    errno.EPERM,
                    errno.EOPNOTSUPP,
                    errno.ENOSYS,
                    errno.EINVAL,
                ):
                    raise
                # Some destination filesystems do not support hard links. An
                # exclusive copy retains the same no-overwrite guarantee.
                with source.open("rb") as origin, target.open("xb") as destination:
                    created.append((target, os.fstat(destination.fileno())))
                    shutil.copyfileobj(origin, destination, length=1024 * 1024)
            else:
                created.append((target, source.stat()))
    except BaseException:
        for target, identity in reversed(created):
            try:
                if os.path.samestat(target.stat(), identity):
                    target.unlink()
            except FileNotFoundError:
                pass
        raise


@contextmanager
def staged_output(output, workspace_name=None):
    folder = Path(output.output_folder)
    folder.mkdir(parents=True, exist_ok=True)
    stage = folder / (workspace_name or f".ogre-plugin-{uuid4().hex}")
    stage.mkdir(mode=0o700)
    staged = copy.deepcopy(output)
    staged.output_folder = str(stage)
    try:
        yield staged
    finally:
        try:
            # Parser reports may contain both valid records and errors. Keep
            # those useful partial results while retaining a nonzero exit code.
            publish_files(stage, folder)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
