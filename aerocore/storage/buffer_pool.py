from dataclasses import dataclass
from .policies import make_policy


@dataclass
class Frame:
    page: object
    pin_count: int = 0
    dirty: bool = False


class BufferPool:
    def __init__(self, disk_manager, capacity=8, policy="lru"):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.disk = disk_manager
        self.capacity = capacity
        self.policy = make_policy(policy)
        self.frames = {}
        self.stats = {"hits": 0, "misses": 0, "evictions": 0,
                      "disk_reads": 0, "disk_writes": 0}

    def fetch_page(self, page_id):
        if page_id not in self.frames and not 0 <= page_id < self.disk.page_count:
            raise ValueError(f"Unknown page id: {page_id}")  # fail before evicting anything
        if page_id in self.frames:
            self.stats["hits"] += 1
            frame = self.frames[page_id]
            frame.pin_count += 1
            self.policy.record_access(page_id)
            return frame.page

        self.stats["misses"] += 1
        if len(self.frames) >= self.capacity:
            candidates = {pid for pid, frame in self.frames.items() if frame.pin_count == 0}
            victim = self.policy.evict(candidates)
            if victim is None:
                raise RuntimeError("All buffer frames are pinned; cannot evict a page")
            self._evict(victim)

        page = self.disk.read_page(page_id)
        self.stats["disk_reads"] += 1
        self.frames[page_id] = Frame(page=page, pin_count=1)
        self.policy.record_access(page_id)
        return page

    def new_page(self):
        """Allocate a page on disk and return (page_id, pinned page)."""
        page_id = self.disk.allocate_page()
        return page_id, self.fetch_page(page_id)

    def _evict(self, page_id):
        frame = self.frames[page_id]
        if frame.dirty:
            self.disk.write_page(page_id, frame.page.serialize())
            self.stats["disk_writes"] += 1
        del self.frames[page_id]
        self.policy.remove(page_id)
        self.stats["evictions"] += 1

    def unpin_page(self, page_id, dirty=False):
        if page_id not in self.frames:
            return False
        frame = self.frames[page_id]
        if frame.pin_count == 0:
            return False
        frame.pin_count -= 1
        frame.dirty = frame.dirty or dirty
        return True

    def flush_page(self, page_id):
        frame = self.frames.get(page_id)
        if frame is None:
            return False
        if frame.dirty:
            self.disk.write_page(page_id, frame.page.serialize())
            self.stats["disk_writes"] += 1
            frame.dirty = False
        return True

    def flush_all(self):
        for page_id in list(self.frames):
            self.flush_page(page_id)

    def close(self):
        self.flush_all()