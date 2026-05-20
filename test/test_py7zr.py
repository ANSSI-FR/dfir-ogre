import os
import shutil
from typing import Optional
from unittest import TestCase, mock
import py7zr
from py7zr.io import Py7zIO, WriterFactory

from . import TEMP_FOLDER

class TestPy7zr(TestCase):
  # python -m unittest test.test_py7zr.TestPy7zr.test_stream -v
  def test_stream(self):
    archive = os.path.join("test", "data","archive", "secret.7z")
    extract_path = os.path.join(".tmp", "py7zr")
    shutil.rmtree(extract_path, ignore_errors=True)

    os.makedirs(extract_path, exist_ok=True)
    factory = StreamIOFactory()
    with py7zr.SevenZipFile(archive, 'r', password="password") as archive:
        archive.extract(extract_path, targets=["folder/lorem.txt", "hello.txt"], factory=factory)

    with open(os.path.join(extract_path,"folder", "lorem.txt"),"r" ) as f:
        content = f.read()
        assert("mollit anim id est laborum." in content)
        self.assertEqual(len(content),447)

    with open(os.path.join(extract_path, "hello.txt"),"r" ) as f:
        content = f.read()

        self.assertEqual(len(content),13)
        self.assertEqual("Hello world!\n",content)


class StreamIO(Py7zIO):
    def __init__(self, fname: str):
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        self.writer = open(fname, 'wb')
        self.fname = fname
        self.length = 0

    def write(self, s: bytes| bytearray)->int:
        to_write = len(s)
        self.length += to_write
        self.writer.write(s)
        return to_write

    def flush(self) -> None:
        self.writer.flush()

    def __del__(self):
        self.writer.close()

    def size(self) -> int:
        return self.length

    def read(self, size: Optional[int] = None) -> bytes:
        return b''

    def seek(self, offset: int, whence: int = 0) -> int:
        return 0


class StreamIOFactory(WriterFactory):
    """Factory class to return StreamWriter object."""
    def create(self, filename: str) -> Py7zIO:
        product = StreamIO(filename)
        return product
