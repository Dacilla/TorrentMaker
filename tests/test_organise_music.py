from organiseMusic import cleanup_empty_source_dirs


def test_cleanup_empty_source_dirs_removes_empty_source_parents(tmp_path):
    source_dir = tmp_path / "incoming" / "album" / "disc"
    source_dir.mkdir(parents=True)

    cleanup_empty_source_dirs(tmp_path, {source_dir})

    assert tmp_path.exists()
    assert not (tmp_path / "incoming").exists()


def test_cleanup_empty_source_dirs_preserves_unrelated_empty_dirs(tmp_path):
    source_dir = tmp_path / "incoming" / "album"
    source_dir.mkdir(parents=True)
    unrelated = tmp_path / "keep-me"
    unrelated.mkdir()

    cleanup_empty_source_dirs(tmp_path, {source_dir})

    assert unrelated.exists()


def test_cleanup_empty_source_dirs_stops_at_non_empty_parent(tmp_path):
    source_dir = tmp_path / "incoming" / "album"
    source_dir.mkdir(parents=True)
    marker = tmp_path / "incoming" / "notes.txt"
    marker.write_text("keep parent", encoding="utf-8")

    cleanup_empty_source_dirs(tmp_path, {source_dir})

    assert not source_dir.exists()
    assert marker.exists()
    assert marker.parent.exists()
