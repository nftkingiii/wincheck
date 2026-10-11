tox-dev/tox (written report): UNC paths in `commands` lose a leading backslash on Windows

On Windows, a command in `tox.ini` that refers to a network share or an extended-length path gets a
mangled argument. The leading `\\` of the path turns into a single `\`, so the command can't find the file.

```ini
[testenv]
commands = xcopy \\server\share\file.txt .
```

`tox c -k commands` shows the argument as `\server\share\file.txt` instead of `\\server\share\file.txt`.
The same happens when the path is quoted (`"\\server\share\file name"`), when it is an option value
(`--source=\\server\share`), and for `\\?\C:\...` and `\\.\pipe\...` paths.

Expected: on Windows, UNC, extended-length and device paths keep both leading backslashes when tox splits
the command line.
