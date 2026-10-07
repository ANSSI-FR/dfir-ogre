from unittest import TestCase

from dfir_ogre_common import OutputConfiguration


def _output(name: str = "a_b_c_file") -> OutputConfiguration:
    return OutputConfiguration(
        base_file_name=name,
        output_folder="output/raw",
        output_type="file",
        format="jsonl",
        date_format="iso",
        with_timeline=False,
        timeline_include_undated=False,
        include_empty=False,
        params={},
    )


class TestOutputNameRegistry(TestCase):
    def test_flattened_paths_from_two_archives_receive_stable_distinct_names(self):
        from ogre.output_naming import OutputNameRegistry

        def assign(keys):
            registry = OutputNameRegistry()
            outputs = {key: _output() for key in keys}
            for key in keys:
                registry.register(
                    outputs[key],
                    source_key=key,
                    mapping_label="event",
                    output_name="raw",
                    uses_relative_path=True,
                )
            registry.finalize()
            return {key: output.base_file_name for key, output in outputs.items()}

        first = "main-a.7z::a/b_c/file"
        second = "main-b.7z::a/b/c/file"
        forward = assign([first, second])
        reverse = assign([second, first])

        self.assertNotEqual(forward[first], forward[second])
        self.assertTrue(all(name.startswith("a_b_c_file__") for name in forward.values()))
        self.assertEqual(forward, reverse)

    def test_new_relative_path_name_moves_around_legacy_collision(self):
        from ogre.output_naming import OutputNameRegistry

        legacy = _output()
        relative = _output()
        registry = OutputNameRegistry()
        registry.register(
            legacy,
            source_key="legacy",
            mapping_label="event",
            output_name="raw",
            uses_relative_path=False,
        )
        registry.register(
            relative,
            source_key="folder::a/b/c/file",
            mapping_label="event",
            output_name="raw",
            uses_relative_path=True,
        )
        registry.finalize()

        self.assertEqual(legacy.base_file_name, "a_b_c_file")
        self.assertNotEqual(relative.base_file_name, legacy.base_file_name)

    def test_generated_name_skips_a_preexisting_matching_suffix(self):
        from ogre.output_naming import OutputNameRegistry

        def candidate(include_reserved):
            first = _output("file")
            second = _output("file")
            registry = OutputNameRegistry()
            registry.register(
                first,
                source_key="folder::one/file",
                mapping_label="event",
                output_name="raw",
                uses_relative_path=True,
            )
            registry.register(
                second,
                source_key="folder::two/file",
                mapping_label="event",
                output_name="raw",
                uses_relative_path=True,
            )
            reserved = None
            if include_reserved:
                reserved = _output(candidate(False)[0])
                registry.register(
                    reserved,
                    source_key="legacy",
                    mapping_label="event",
                    output_name="raw",
                    uses_relative_path=False,
                )
            registry.finalize()
            return first.base_file_name, second.base_file_name, reserved

        first_name, second_name, reserved = candidate(True)
        self.assertIsNotNone(reserved)
        self.assertNotEqual(first_name, reserved.base_file_name)
        self.assertNotEqual(first_name, second_name)
