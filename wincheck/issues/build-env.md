pypa/build (written report): isolated builds never use symlinks on Windows, even when symlinks are enabled

On Windows with Developer Mode on (so unprivileged users can create symlinks), `python -m build` still
creates its isolated environments as if the file system did not support symlinks.

`build.env._fs_supports_symlink()` returns `False` on this machine, although `os.symlink()` works when
called directly on two files in the temp directory.

Expected: `_fs_supports_symlink()` returns `True` on Windows when symlinks can be created.
