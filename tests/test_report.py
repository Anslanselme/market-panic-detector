import pandas as pd

from panic_detector import report


def test_interpretation_block_is_preserved(tmp_path):
    path = tmp_path / "findings.md"
    assert report.existing_interpretation(path) == report.DEFAULT_INTERPRETATION
    path.write_text(
        f"# x\n{report.INTERP_START}\nMy own reading.\n{report.INTERP_END}\nrest", encoding="utf-8"
    )
    assert report.existing_interpretation(path) == "My own reading."


def test_md_table_formats_and_handles_missing():
    df = pd.DataFrame({"a": [0.123456, float("nan")], "b": ["x", None]})
    text = report.md_table(df, {"a": "{:.2f}"})
    lines = text.splitlines()
    assert lines[0] == "| a | b |"
    assert lines[2] == "| 0.12 | x |"
    assert lines[3] == "| – | – |"
