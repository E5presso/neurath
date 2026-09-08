"""Kernel file events close the gap between durable commit and socket notification.

No interval scan or receiver agent is created. Wait deadlines belong exclusively
to individual unacknowledged message retries. SQLite state remains authoritative;
filesystem notifications merely request a fresh read, including on queue overflow.
"""

import ctypes
import os
import select
import struct
import sys
from pathlib import Path


class StoreEvents:
    def __init__(self, database, receiver):
        self.database = Path(database)
        self.receiver = receiver
        self._queue = None
        self._inotify = None
        self._files = {}
        try:
            if hasattr(select, "kqueue"):
                self._queue = select.kqueue()
                self._queue.control([select.kevent(receiver.fileno(), filter=select.KQ_FILTER_READ,
                    flags=select.KQ_EV_ADD)], 0, 0)
                self._refresh_files()
            elif sys.platform.startswith("linux"):
                libc = ctypes.CDLL(None, use_errno=True)
                libc.inotify_init1.argtypes = [ctypes.c_int]
                libc.inotify_init1.restype = ctypes.c_int
                libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
                libc.inotify_add_watch.restype = ctypes.c_int
                self._inotify = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
                if self._inotify < 0:
                    self._inotify = None
                    raise OSError(ctypes.get_errno(), "cannot create store event queue")
                # Directory child modifications cover an already existing WAL.
                # IN_MODIFY | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE |
                # IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF. Avoid close/access
                # notifications from our own read-only transactions.
                mask = 0x2 | 0x40 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800
                if libc.inotify_add_watch(self._inotify, os.fsencode(self.database.parent), mask) < 0:
                    raise OSError(ctypes.get_errno(), "cannot watch message store")
            else:
                raise OSError("native message-store event observation is unavailable")
        except BaseException:
            self.close()
            raise

    def _refresh_files(self):
        paths = {self.database.parent, self.database}
        paths.update(Path(str(self.database) + suffix) for suffix in ("-wal", "-journal")
                     if Path(str(self.database) + suffix).exists())
        for path, (descriptor, inode) in list(self._files.items()):
            try:
                current = path.stat(follow_symlinks=False)
                unchanged = (current.st_dev, current.st_ino) == inode
            except FileNotFoundError:
                unchanged = False
            if path not in paths or not unchanged:
                os.close(descriptor)
                del self._files[path]
        for path in paths - self._files.keys():
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:
                continue  # Transient rollback journals can disappear after commit.
            status = os.fstat(descriptor)
            self._files[path] = (descriptor, (status.st_dev, status.st_ino))
            self._queue.control([select.kevent(descriptor, filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)], 0, 0)

    def wait(self, timeout=None):
        """Wait for a socket or actual store change, optionally until one message retry."""
        changed = False
        socket_ready = False
        if self._queue is not None:
            events = self._queue.control(None, 64, timeout)
            for event in events:
                if event.flags & select.KQ_EV_ERROR:
                    raise OSError(event.data, "message store event observation failed")
                if event.filter == select.KQ_FILTER_READ and event.ident == self.receiver.fileno():
                    socket_ready = True
                elif event.filter == select.KQ_FILTER_VNODE:
                    changed = True
            if changed:
                self._refresh_files()
        else:
            ready, _, _ = select.select([self._inotify, self.receiver], [], [], timeout)
            if self._inotify in ready:
                # Every queue event, including overflow, causes an authoritative
                # read. No filename or message body from an OS event is trusted.
                payload = os.read(self._inotify, 65536)
                offset = 0
                while offset + 16 <= len(payload):
                    _, mask, _, length = struct.unpack_from("iIII", payload, offset)
                    if mask & (0x400 | 0x800 | 0x8000):  # directory deleted/moved/watch ignored
                        raise OSError("message store directory watch was invalidated")
                    offset += 16 + length
                changed = True
            socket_ready = self.receiver in ready
        payload = b""
        if socket_ready:
            try:
                payload = self.receiver.recv(65)
            except BlockingIOError:
                pass
        return payload, changed

    def close(self):
        for descriptor, _ in self._files.values():
            os.close(descriptor)
        self._files.clear()
        if self._queue is not None:
            self._queue.close()
            self._queue = None
        if self._inotify is not None:
            os.close(self._inotify)
            self._inotify = None
