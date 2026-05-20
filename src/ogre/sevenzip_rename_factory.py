import os
import shutil
from typing import Optional
from unittest import TestCase, mock
import py7zr
import hashlib
from py7zr.io import Py7zIO, WriterFactory
MAX_FILE_NAME_BYTE_LENGTH = 240
class _StreamIO(Py7zIO):
 
    def __init__(self, fname: str):
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        self.writer = open(fname, 'wb')
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


class RenameFactory(WriterFactory):
    """Factory class to return StreamWriter object."""
    def create(self, filename: str) -> Py7zIO:
        name = rename_file(filename)
        return _StreamIO(name)

def need_rename(path:str)-> bool:
    sample_file_name = os.path.basename(path)
    sample_file_name_bytes = sample_file_name.encode('utf-8')
    return len(sample_file_name_bytes) > MAX_FILE_NAME_BYTE_LENGTH

def rename_file(path:str)->str:
    sample_file_dir = os.path.dirname(path)
    sample_file_name = os.path.basename(path)
    sample_file_name_bytes = sample_file_name.encode('utf-8')

    hash_obj =hashlib.sha256(sample_file_name_bytes)
    hex_hash = hash_obj.hexdigest()
    return os.path.join(sample_file_dir, hex_hash)
