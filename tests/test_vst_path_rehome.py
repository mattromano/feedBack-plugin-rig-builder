from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _routes_module():
    spec = importlib.util.spec_from_file_location("rig_builder_routes_for_rehome_test", ROOT / "routes.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE preset_pieces ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, preset_id INTEGER NOT NULL DEFAULT 0, "
        "vst_path TEXT, vst_format TEXT, vst_state TEXT)"
    )
    return conn


def _insert(conn, vst_path):
    cur = conn.execute("INSERT INTO preset_pieces (vst_path) VALUES (?)", (vst_path,))
    return cur.lastrowid


def _path_of(conn, piece_id):
    return conn.execute("SELECT vst_path FROM preset_pieces WHERE id = ?", (piece_id,)).fetchone()[0]


def _expect(plugin_dir, *parts):
    # The migration intentionally emits forward slashes on every OS, so build the
    # expected value the same way (str(Path) is '\'-separated on Windows).
    return str(plugin_dir.joinpath("vst", *parts)).replace("\\", "/")


def test_rehome_repoints_stale_appimage_mount_to_current_plugin_dir(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "opt" / "feedback" / "resources" / "slopsmith" / "plugins" / "rig_builder"
    routes._plugin_dir = plugin_dir

    conn = _make_conn()
    routes._conn = conn
    # A tone saved under a now-dead AppImage FUSE mount.
    stale = "/tmp/.mount_feedbavy7H0S/resources/feedBack/plugins/rig_builder/vst/amps/SamplegSBTCL.vst3"
    pid = _insert(conn, stale)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "amps", "SamplegSBTCL.vst3")


def test_rehome_covers_legacy_nam_rig_builder_marker(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    conn = _make_conn()
    routes._conn = conn
    stale = "/tmp/.mount_feedbaOLD/resources/feedBack/plugins/nam_rig_builder/vst/racks/RB Final Leveler.vst3"
    pid = _insert(conn, stale)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "racks", "RB Final Leveler.vst3")


def test_rehome_handles_backslash_windows_style_paths(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    conn = _make_conn()
    routes._conn = conn
    # A tone saved on Windows: backslash separators, win-unpacked prefix.
    stale = r"C:\Users\me\FeedBack Test\win-unpacked\resources\slopsmith\plugins\rig_builder\vst\amps\DSL100.vst3"
    pid = _insert(conn, stale)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "amps", "DSL100.vst3")


def test_rehome_emits_forward_slashes_for_flat_backslash_path(tmp_path):
    # A flat (pre-subdir-reorg) Windows path must come out prefix-repaired AND
    # forward-slashed, so the slash-only subdir/rename migrations that run after
    # re-home can then match '/vst/<name>' and fix the flat tail.
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    conn = _make_conn()
    routes._conn = conn
    stale = r"C:\win-unpacked\resources\slopsmith\plugins\rig_builder\vst\DSL100.vst3"
    pid = _insert(conn, stale)

    routes._migrate_rehome_bundled_vst_paths()

    out = _path_of(conn, pid)
    assert "\\" not in out
    assert out == _expect(plugin_dir, "DSL100.vst3")


def test_rehome_normalizes_already_live_backslash_path(tmp_path):
    # A row already pointing at the current plugin dir but with '\' separators
    # (Windows) must still be forward-slashed, or the later slash-only subdir/
    # rename migrations can't match it to repair a flat/renamed tail.
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    conn = _make_conn()
    routes._conn = conn
    live_backslash = str(plugin_dir.joinpath("vst", "amps", "DSL100.vst3")).replace("/", "\\")
    pid = _insert(conn, live_backslash)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "amps", "DSL100.vst3")


def test_rehome_leaves_external_and_correct_paths_untouched(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    conn = _make_conn()
    routes._conn = conn

    external = "/home/byron/.vst3/MyFavouriteAmp.vst3"          # user VST, no bundled marker
    already = _expect(plugin_dir, "amps", "DSL100.vst3")  # already anchored (forward-slash) at live dir
    ext_id = _insert(conn, external)
    ok_id = _insert(conn, already)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, ext_id) == external
    assert _path_of(conn, ok_id) == already


def test_rehome_is_noop_without_vst_path_column(tmp_path):
    routes = _routes_module()
    routes._plugin_dir = tmp_path / "rig_builder"
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE preset_pieces (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    routes._conn = conn
    # Must not raise even though vst_path does not exist yet.
    routes._migrate_rehome_bundled_vst_paths()


def _make_bundle(root: Path, rel: str) -> None:
    (root / rel).mkdir(parents=True)  # a .vst3 is a bundle directory


def _norm(p: Path) -> str:
    return str(p).replace("\\", "/")


def test_rehome_prefers_download_root_when_plugin_dir_has_no_vst(tmp_path):
    # Packaged builds ship without <plugin>/vst; the packs live in the
    # downloaded root under the config dir. A tone saved by an older build
    # must land THERE, not on the empty plugin dir (every song tone broke).
    routes = _routes_module()
    plugin_dir = tmp_path / "app" / "resources" / "slopsmith" / "plugins" / "rig_builder"
    plugin_dir.mkdir(parents=True)
    routes._plugin_dir = plugin_dir
    routes._config_dir = tmp_path / "config"
    dl_root = routes._downloaded_vst_root()
    _make_bundle(dl_root, "pedals/GE-8.vst3")

    conn = _make_conn()
    routes._conn = conn
    stale = r"C:\old\win-unpacked\resources\slopsmith\plugins\rig_builder\vst\pedals\GE-8.vst3"
    pid = _insert(conn, stale)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _norm(dl_root / "pedals" / "GE-8.vst3")


def test_rehome_prefers_plugin_dir_when_both_roots_have_the_bundle(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    routes._config_dir = tmp_path / "config"
    _make_bundle(plugin_dir / "vst", "amps/DSL100.vst3")
    _make_bundle(routes._downloaded_vst_root(), "amps/DSL100.vst3")

    conn = _make_conn()
    routes._conn = conn
    pid = _insert(conn, "/somewhere/else/plugins/rig_builder/vst/amps/DSL100.vst3")

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "amps", "DSL100.vst3")


def test_rehome_moves_download_root_path_to_plugin_dir_copy(tmp_path):
    # A path already under the download root is recognised as bundled too:
    # if only the plugin dir has that bundle now, follow it there.
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    routes._config_dir = tmp_path / "config"
    _make_bundle(plugin_dir / "vst", "pedals/FM101.vst3")
    dl_path = _norm(routes._downloaded_vst_root() / "pedals" / "FM101.vst3")

    conn = _make_conn()
    routes._conn = conn
    pid = _insert(conn, dl_path)

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "pedals", "FM101.vst3")


def test_rehome_falls_back_to_plugin_dir_when_no_root_has_it(tmp_path):
    routes = _routes_module()
    plugin_dir = tmp_path / "rig_builder"
    routes._plugin_dir = plugin_dir
    routes._config_dir = tmp_path / "config"
    routes._downloaded_vst_root().mkdir(parents=True)

    conn = _make_conn()
    routes._conn = conn
    pid = _insert(conn, "/gone/plugins/rig_builder/vst/racks/LNG.vst3")

    routes._migrate_rehome_bundled_vst_paths()

    assert _path_of(conn, pid) == _expect(plugin_dir, "racks", "LNG.vst3")
