
import struct

PAGE_SIZE = 4096
_MAGIC = b"ACPG"

# Page header: magic, page_id, slot_count, free_start, free_end
_HEADER = struct.Struct(">4sIHHH")

# Each slot stores: record offset and record length
_SLOT = struct.Struct(">HH")


class Page:
    """A fixed-size slotted page that stores records as bytes."""

    def __init__(self, page_id):
        self.page_id = int(page_id)
        self.slots = []
        self.data = bytearray(PAGE_SIZE)

        self.free_start = _HEADER.size
        self.free_end = PAGE_SIZE

    def get_free_space(self):
        """Return the available space between the slot directory and records."""
        return self.free_end - self.free_start

    def _compact(self):
        """Move records together without changing their slot IDs."""

        live_records = []

        for offset, length in self.slots:
            if length == 0:
                live_records.append(None)
            else:
                record = bytes(self.data[offset:offset + length])
                live_records.append(record)

        self.data = bytearray(PAGE_SIZE)

        # Keep the existing number of slots, including deleted slots.
        self.free_start = _HEADER.size + len(self.slots) * _SLOT.size
        self.free_end = PAGE_SIZE

        new_slots = []

        for record in live_records:
            if record is None:
                new_slots.append((0, 0))
            else:
                self.free_end -= len(record)

                self.data[
                    self.free_end:self.free_end + len(record)
                ] = record

                new_slots.append((self.free_end, len(record)))

        self.slots = new_slots

    def insert_record(self, record):
        """Insert a record and return its slot ID."""

        if not isinstance(record, (bytes, bytearray)):
            raise TypeError("record must be bytes or bytearray")

        record = bytes(record)

        # Find a deleted slot that can be reused.
        reusable = next(
            (i for i, (_, length) in enumerate(self.slots) if length == 0),
            None
        )

        # A new slot needs extra space in the slot directory.
        needed_slot = 0 if reusable is not None else _SLOT.size

        # Compact the page if there is not enough continuous space.
        if len(record) + needed_slot > self.get_free_space():
            self._compact()

        # Check again after compaction.
        if len(record) + needed_slot > self.get_free_space():
            return None

        # Store the record from the end of the page backwards.
        self.free_end -= len(record)

        self.data[
            self.free_end:self.free_end + len(record)
        ] = record

        if reusable is not None:
            self.slots[reusable] = (self.free_end, len(record))
            return reusable

        # Create a new slot.
        slot_id = len(self.slots)

        self.slots.append((self.free_end, len(record)))
        self.free_start += _SLOT.size

        return slot_id

    def get_record(self, slot_id):
        """Return a record using its slot ID."""

        if not 0 <= slot_id < len(self.slots):
            return None

        offset, length = self.slots[slot_id]

        if length == 0:
            return None

        return bytes(self.data[offset:offset + length])

    def delete_record(self, slot_id):
        """Delete a record without changing other slot IDs."""

        if not 0 <= slot_id < len(self.slots):
            return False

        offset, length = self.slots[slot_id]

        if length == 0:
            return False

        # Mark the slot as deleted.
        self.slots[slot_id] = (0, 0)

        # Compact the remaining records.
        self._compact()

        return True

    def serialize(self):
        """Convert the page into exactly 4096 bytes."""

        output = bytearray(PAGE_SIZE)

        output[:_HEADER.size] = _HEADER.pack(
            _MAGIC,
            self.page_id,
            len(self.slots),
            self.free_start,
            self.free_end
        )

        # Save the slot directory.
        pos = _HEADER.size

        for offset, length in self.slots:
            output[pos:pos + _SLOT.size] = _SLOT.pack(
                offset,
                length
            )
            pos += _SLOT.size

        # Save the actual record data.
        output[self.free_end:] = self.data[self.free_end:]

        return bytes(output)

    @classmethod
    def deserialize(cls, raw):
        """Reconstruct a Page from its serialized bytes."""

        if len(raw) != PAGE_SIZE:
            raise ValueError(
                f"A page must be exactly {PAGE_SIZE} bytes"
            )

        magic, page_id, slot_count, free_start, free_end = (
            _HEADER.unpack(raw[:_HEADER.size])
        )

        if magic != _MAGIC:
            raise ValueError("Invalid AeroCore page")

        page = cls(page_id)

        page.data = bytearray(raw)
        page.free_start = free_start
        page.free_end = free_end

        page.slots = []

        pos = _HEADER.size

        for _ in range(slot_count):
            slot = _SLOT.unpack(raw[pos:pos + _SLOT.size])
            page.slots.append(slot)
            pos += _SLOT.size

        return page

    def __len__(self):
        """Return the number of active records."""

        return sum(
            1 for _, length in self.slots if length > 0
        )
