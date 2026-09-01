import pytest

from quiver.errors import AimError
from quiver.registry import AppEntry


def make_entry(alias="foo", **kwargs):
    params = dict(
        alias=alias,
        name="Foo App",
        path=f"/tmp/{alias}.AppImage",
        version="1.0.0",
        arch="x86_64",
        categories=["Utility"],
        exec_args=["--flag"],
        source_opts={"asset_patterns": ["*.AppImage"]},
    )
    params.update(kwargs)
    return AppEntry(**params)


def test_add_get_roundtrip(registry):
    registry.add(make_entry())
    loaded = registry.require("foo")
    assert loaded.name == "Foo App"
    assert loaded.exec_args == ["--flag"]
    assert loaded.source_opts == {"asset_patterns": ["*.AppImage"]}
    assert loaded.integrated is False


def test_duplicate_alias_rejected(registry):
    registry.add(make_entry())
    with pytest.raises(AimError, match="already registered"):
        registry.add(make_entry())


def test_require_missing_raises(registry):
    from quiver.errors import NotFoundError

    with pytest.raises(NotFoundError):
        registry.require("ghost")


def test_update_fields(registry):
    registry.add(make_entry())
    updated = registry.update("foo", version="2.0.0", integrated=True)
    assert updated.version == "2.0.0"
    assert updated.integrated is True
    assert registry.require("foo").version == "2.0.0"


def test_remove(registry):
    registry.add(make_entry())
    registry.add_history("foo", action="added", path="/tmp/foo.AppImage")
    registry.remove("foo")
    assert registry.get("foo") is None
    assert registry.history("foo") == []


def test_find_by_path(registry, tmp_path):
    target = tmp_path / "bar.AppImage"
    target.write_bytes(b"x")
    registry.add(make_entry(alias="bar", path=str(target)))
    assert registry.find_by_path(target).alias == "bar"
    assert registry.find_by_path(tmp_path / "other.AppImage") is None


def test_history_order_and_prune(registry):
    registry.add(make_entry())
    for version in ["1.0", "1.1", "1.2", "1.3"]:
        registry.add_history("foo", action="updated", version=version, path="/tmp/foo.AppImage")
    history = registry.history("foo")
    assert [h.version for h in history] == ["1.3", "1.2", "1.1", "1.0"]
    removed = registry.prune_history("foo", keep=2)
    assert [h.version for h in removed] == ["1.1", "1.0"]
    assert len(registry.history("foo")) == 2


def test_all_sorted_by_name(registry):
    registry.add(make_entry(alias="zeta", name="Zeta"))
    registry.add(make_entry(alias="alpha", name="Alpha"))
    assert [e.alias for e in registry.all()] == ["alpha", "zeta"]


def test_last_check_result_roundtrip(registry):
    registry.add(make_entry())
    registry.update("foo", last_check_result={"status": "up_to_date"}, last_check_at="2026-08-31")
    assert registry.require("foo").last_check_result == {"status": "up_to_date"}
