import logging
from unittest import TestCase

from ogre.logging import init_logger


class TestLogging(TestCase):
    def test_init_logger_does_not_duplicate_console_handler(self):
        root_logger = logging.getLogger()

        init_logger()
        after_first = self._ogre_console_handler_count(root_logger)

        init_logger()
        after_second = self._ogre_console_handler_count(root_logger)

        self.assertGreaterEqual(after_first, 1)
        self.assertEqual(after_first, after_second)

    def _ogre_console_handler_count(self, root_logger):
        return len(
            [
                handler
                for handler in root_logger.handlers
                if getattr(handler, "_ogre_console_handler", False)
            ]
        )
